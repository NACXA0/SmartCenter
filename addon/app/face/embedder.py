from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    model_version: str
    ready: bool = False

    @abstractmethod
    def embed(self, image_bgr: np.ndarray) -> tuple[np.ndarray | None, dict]:
        """返回 (L2 归一化向量, 元数据)。失败时向量为 None。"""


class MockEmbedder(Embedder):
    """开发/单测：用图像均值哈希成固定维向量；可注入质量元数据。"""

    def __init__(self, model_version: str = "mock-v1", dim: int = 128) -> None:
        self.model_version = model_version
        self.dim = dim
        self.ready = True
        self._force_meta: dict | None = None

    def force_meta(self, meta: dict | None) -> None:
        self._force_meta = meta

    def embed(self, image_bgr: np.ndarray) -> tuple[np.ndarray | None, dict]:
        if not self.ready:
            return None, {"ok": False, "reason": "model_not_loaded"}
        img = np.asarray(image_bgr)
        if img.ndim < 2:
            return None, {"ok": False, "reason": "bad_image"}
        h, w = img.shape[:2]
        meta = {
            "ok": True,
            "det_score": 0.99,
            "box_w": float(w),
            "box_h": float(h),
            "landmarks": 5,
            "blur": 0.05,
            "yaw": 0.0,
            "is_gray": bool(img.ndim == 2 or (img.ndim == 3 and abs(float(img[..., 0].mean() - img[..., 2].mean())) < 1.0)),
        }
        if self._force_meta:
            meta.update(self._force_meta)
        if not meta.get("ok", True):
            return None, meta
        # 稳定伪嵌入：由像素统计驱动，同图同向量
        rng = np.random.default_rng(int(img.mean() * 1000) % (2**32))
        seed_extra = int(img.std() * 1000) % 997
        rng2 = np.random.default_rng(seed_extra + 1)
        vec = rng.standard_normal(self.dim).astype(np.float32) + 0.01 * rng2.standard_normal(self.dim).astype(np.float32)
        # 若调用方在 meta 里塞了 identity_key，则固定身份向量（测比对用）
        key = meta.get("identity_key")
        if key is not None:
            rng3 = np.random.default_rng(abs(hash(str(key))) % (2**32))
            vec = rng3.standard_normal(self.dim).astype(np.float32)
        n = float(np.linalg.norm(vec) + 1e-9)
        vec = vec / n
        return vec, meta


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def build_embedder(kind: str, model_version: str) -> Embedder:
    if kind == "onnx":
        # 生产可替换为 ONNX ArcFace；未配置模型时退回 mock 并 ready=False
        emb = MockEmbedder(model_version=model_version)
        emb.ready = False
        emb.model_version = model_version
        return emb
    return MockEmbedder(model_version=model_version)
