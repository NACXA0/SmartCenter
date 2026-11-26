from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityConfig:
    min_det_score: float = 0.5
    min_box_px: float = 48.0
    min_landmarks: int = 5
    max_blur: float = 0.35
    max_yaw_abs: float = 25.0
    reject_gray: bool = True
    # 采集防静止照片：相邻合格嵌入余弦若 > 此值视为几乎不动
    max_static_cosine: float = 0.998


def evaluate_meta(meta: dict, cfg: QualityConfig | None = None) -> tuple[bool, str]:
    cfg = cfg or QualityConfig()
    if meta.get("is_gray") and cfg.reject_gray:
        return False, "infrared_or_gray"
    if float(meta.get("det_score", 0)) < cfg.min_det_score:
        return False, "low_det_score"
    if float(meta.get("box_w", 0)) < cfg.min_box_px or float(meta.get("box_h", 0)) < cfg.min_box_px:
        return False, "face_too_small"
    if int(meta.get("landmarks", 0)) < cfg.min_landmarks:
        return False, "landmarks_missing"
    if float(meta.get("blur", 1)) > cfg.max_blur:
        return False, "too_blurry"
    if abs(float(meta.get("yaw", 0))) > cfg.max_yaw_abs:
        return False, "not_frontal"
    if meta.get("ok") is False:
        return False, str(meta.get("reason") or "reject")
    return True, "ok"


REASON_HINTS = {
    "infrared_or_gray": "请在彩色光线下正对摄像头",
    "low_det_score": "未看清人脸，请靠近并正对",
    "face_too_small": "再近一点",
    "landmarks_missing": "请正对，露出五官",
    "too_blurry": "请保持稳定，光线再亮一点",
    "not_frontal": "请正对摄像头",
    "static_photo": "请轻微转头，不要举照片",
    "model_not_loaded": "人脸服务未就绪",
    "ok": "好的，请保持",
}
