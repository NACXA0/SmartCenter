from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
import io

from .embedder import Embedder, cosine
from .quality import QualityConfig, REASON_HINTS, evaluate_meta
from ..store import GalleryStore


@dataclass
class EnrollSession:
    session_id: str
    user_id: str
    display_name: str
    channel: str  # student | staff
    actor: str
    created_at: float
    vectors: list[np.ndarray] = field(default_factory=list)
    frame_paths: list[str | None] = field(default_factory=list)
    needed: int = 5


class SessionManager:
    def __init__(
        self,
        store: GalleryStore,
        embedder: Embedder,
        frames_dir: Path,
        needed: int = 5,
        quality: QualityConfig | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.frames_dir = frames_dir
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.needed = needed
        self.quality = quality or QualityConfig()
        self._sessions: dict[str, EnrollSession] = {}
        self._by_user: dict[str, str] = {}

    def start(self, user_id: str, display_name: str, channel: str, actor: str) -> EnrollSession:
        if not self.embedder.ready:
            raise RuntimeError("model_not_loaded")
        existing = self._by_user.get(user_id)
        if existing and existing in self._sessions:
            raise RuntimeError("session_already_open")
        sid = uuid.uuid4().hex
        sess = EnrollSession(
            session_id=sid,
            user_id=str(user_id),
            display_name=display_name or str(user_id),
            channel=channel,
            actor=actor,
            created_at=time.time(),
            needed=self.needed,
        )
        self._sessions[sid] = sess
        self._by_user[user_id] = sid
        self.store.upsert_person(user_id, sess.display_name, "pending", enabled=True)
        return sess

    def get(self, session_id: str) -> EnrollSession | None:
        return self._sessions.get(session_id)

    def cancel(self, session_id: str, *, drop_frames: bool = True) -> None:
        sess = self._sessions.pop(session_id, None)
        if not sess:
            return
        self._by_user.pop(sess.user_id, None)
        if drop_frames:
            for fp in sess.frame_paths:
                if not fp:
                    continue
                try:
                    Path(fp).unlink(missing_ok=True)
                except Exception:
                    pass

    def expire_stale(self, ttl_sec: float = 1800.0) -> int:
        """丢弃超时未完成的采集会话，避免管理员关页后内存/半成品帧常驻。"""
        now = time.time()
        ttl = max(60.0, float(ttl_sec))
        stale = [sid for sid, s in self._sessions.items() if now - s.created_at > ttl]
        for sid in stale:
            self.cancel(sid, drop_frames=True)
        return len(stale)

    def push_jpeg(self, session_id: str, jpeg: bytes, expected_user_id: str | None = None) -> dict:
        sess = self._sessions.get(session_id)
        if not sess:
            return {"ok": False, "reason": "session_not_found", "hint": "请重新开始采集"}
        if expected_user_id is not None and str(expected_user_id) != sess.user_id:
            return {"ok": False, "reason": "user_mismatch", "hint": "会话与用户不匹配"}
        if not self.embedder.ready:
            return {"ok": False, "reason": "model_not_loaded", "hint": REASON_HINTS["model_not_loaded"]}

        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        arr = np.asarray(img)[:, :, ::-1].copy()  # RGB→BGR-ish for API symmetry
        vec, meta = self.embedder.embed(arr)
        ok_q, reason = evaluate_meta(meta, self.quality)
        if not ok_q or vec is None:
            return {
                "ok": False,
                "reason": reason,
                "hint": REASON_HINTS.get(reason, "请调整姿势"),
                "progress": len(sess.vectors),
                "needed": sess.needed,
                "done": False,
            }

        # 防静止照片：与已有合格帧过于相似则拒绝
        for prev in sess.vectors:
            if cosine(prev, vec) >= self.quality.max_static_cosine:
                return {
                    "ok": False,
                    "reason": "static_photo",
                    "hint": REASON_HINTS["static_photo"],
                    "progress": len(sess.vectors),
                    "needed": sess.needed,
                    "done": False,
                }

        path = self.frames_dir / sess.user_id / f"{sess.session_id}_{len(sess.vectors)}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg)
        sess.vectors.append(vec)
        sess.frame_paths.append(str(path))

        if len(sess.vectors) >= sess.needed:
            self.store.commit_enrollment(
                sess.user_id,
                sess.display_name,
                self.embedder.model_version,
                sess.vectors,
                sess.frame_paths,
            )
            self.cancel(session_id, drop_frames=False)
            return {
                "ok": True,
                "reason": "accepted",
                "hint": "采集完成",
                "progress": sess.needed,
                "needed": sess.needed,
                "done": True,
                "face_status": "accepted",
            }

        return {
            "ok": True,
            "reason": "frame_ok",
            "hint": REASON_HINTS["ok"],
            "progress": len(sess.vectors),
            "needed": sess.needed,
            "done": False,
        }
