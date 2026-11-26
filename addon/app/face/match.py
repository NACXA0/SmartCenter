from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from .embedder import Embedder, cosine
from .quality import QualityConfig, evaluate_meta
from ..store import GalleryStore


@dataclass
class MatchConfig:
    match_threshold: float = 0.42
    verify_threshold: float = 0.48
    cooldown_sec: float = 30.0
    required_match_frames: int = 3
    door_node: str = "front_gate"
    door_cameras: list[str] = field(default_factory=list)
    door_zones: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    decision: str  # grant | deny | skip
    reason: str
    user_id: str | None = None
    similarity: float = 0.0
    grant: dict | None = None


class DoorMatcher:
    def __init__(self, store: GalleryStore, embedder: Embedder, cfg: MatchConfig, quality: QualityConfig | None = None) -> None:
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self.quality = quality or QualityConfig()
        self._busy_cameras: set[str] = set()
        self._silent_until: dict[str, float] = {}
        self._recent_events: dict[str, float] = {}
        self._miss_streak: dict[str, int] = {}

    def _event_key(self, camera: str, event_id: str | None) -> str:
        return f"{camera}:{event_id or ''}"

    def should_handle(self, camera: str, zones: list[str], event_id: str | None = None) -> tuple[bool, str]:
        if camera not in self.cfg.door_cameras:
            return False, "not_door_camera"
        if self.cfg.door_zones and not any(z in self.cfg.door_zones for z in zones):
            return False, "zone_miss"
        now = time.monotonic()
        if self._silent_until.get(camera, 0) > now:
            return False, "camera_silenced"
        if camera in self._busy_cameras:
            return False, "busy"
        ek = self._event_key(camera, event_id)
        last = self._recent_events.get(ek, 0)
        if event_id and now - last < 2.0:
            return False, "dedup"
        # 同摄像头短时去重
        cam_last = self._recent_events.get(f"{camera}:*", 0)
        if now - cam_last < 1.0:
            return False, "dedup"
        return True, "ok"

    def _best_user(self, vec: np.ndarray) -> tuple[str | None, float]:
        best_uid, best = None, -1.0
        for uid, vecs in self.store.memory_vectors().items():
            for g in vecs:
                s = cosine(vec, g)
                if s > best:
                    best, best_uid = s, uid
        return best_uid, float(best)

    def match_frames(self, camera: str, frames_bgr: list[np.ndarray], event_id: str | None = None) -> MatchResult:
        if not self.embedder.ready:
            return MatchResult("deny", "model_not_loaded")
        self._busy_cameras.add(camera)
        self._recent_events[f"{camera}:*"] = time.monotonic()
        if event_id:
            self._recent_events[self._event_key(camera, event_id)] = time.monotonic()
        try:
            per_frame: list[tuple[str, float]] = []
            for img in frames_bgr:
                if img.ndim == 2 or (img.ndim == 3 and abs(float(img[..., 0].mean() - img[..., 2].mean())) < 1.5):
                    # 红外/灰度：拒识
                    self.store.audit(None, camera, 0.0, "skip", {"reason": "infrared_or_gray"})
                    return MatchResult("skip", "infrared_or_gray")
                vec, meta = self.embedder.embed(img)
                ok_q, reason = evaluate_meta(meta, self.quality)
                if not ok_q or vec is None:
                    continue
                uid, sim = self._best_user(vec)
                if uid is None or sim < self.cfg.match_threshold:
                    per_frame.append(("?", sim))
                else:
                    p = self.store.get_person(uid)
                    if not p or not p.enabled or p.face_status not in ("accepted", "verified"):
                        per_frame.append(("?", sim))
                    else:
                        per_frame.append((uid, sim))

            if len(per_frame) < self.cfg.required_match_frames:
                self._miss_streak[camera] = self._miss_streak.get(camera, 0) + 1
                if self._miss_streak[camera] >= 5:
                    self._silent_until[camera] = time.monotonic() + min(60.0, 5.0 * self._miss_streak[camera])
                self.store.audit(None, camera, 0.0, "deny", {"reason": "not_enough_frames", "n": len(per_frame)})
                return MatchResult("deny", "not_enough_frames")

            # 多人同框：本窗所有检出身份必须是在册且一致集合内全部匹配
            ids = {u for u, s in per_frame if u != "?"}
            if any(u == "?" for u, _ in per_frame):
                self.store.audit(None, camera, 0.0, "deny", {"reason": "unknown_in_frame"})
                return MatchResult("deny", "unknown_in_frame")
            # 多帧一致性：连续帧同一主身份
            main = per_frame[0][0]
            if any(u != main for u, _ in per_frame):
                # 若是多人且全部在册——计划写死「全部匹配才开」：多人不同 id 且都在册则拒开更安全？
                # 计划：每张脸都匹配到在册才开。这里简化为：多帧须同一人（单人通行）。多人不同 id 拒开。
                self.store.audit(None, camera, 0.0, "deny", {"reason": "multi_identity", "ids": list(ids)})
                return MatchResult("deny", "multi_identity")

            sims = [s for u, s in per_frame if u == main]
            avg_sim = float(sum(sims) / len(sims))
            if self.store.cooldown_active(main, time.monotonic()):
                self.store.audit(main, camera, avg_sim, "skip", {"reason": "cooldown"})
                return MatchResult("skip", "cooldown", user_id=main, similarity=avg_sim)

            # 机会式验证记账
            verify_ok = avg_sim >= self.cfg.verify_threshold
            new_status = self.store.bump_verify(main, verify_ok)
            if new_status == "pending":
                self.store.audit(main, camera, avg_sim, "deny", {"reason": "recollect_required"})
                return MatchResult("deny", "recollect_required", user_id=main, similarity=avg_sim)

            command_id = uuid.uuid4().hex
            if not self.store.mark_grant(command_id):
                return MatchResult("deny", "duplicate_command")

            until_mono = time.monotonic() + self.cfg.cooldown_sec
            self.store.set_cooldown(main, until_mono, time.time() + self.cfg.cooldown_sec)
            self._miss_streak[camera] = 0

            person = self.store.get_person(main)
            grant = {
                "schema": "business.access.grant.v1",
                "node": self.cfg.door_node,
                "door": self.cfg.door_node,
                "ttl_sec": 3,
                "reason": "face_match",
                "subject": {
                    "user_id": main,
                    "display_name": person.display_name if person else main,
                },
                "frigate_event_id": event_id,
                "command_id": command_id,
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 15)),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self.store.audit(main, camera, avg_sim, "grant", {"command_id": command_id, "status": new_status})
            return MatchResult("grant", "face_match", user_id=main, similarity=avg_sim, grant=grant)
        finally:
            self._busy_cameras.discard(camera)

    def prune_recent(self, max_age_sec: float = 300.0) -> int:
        """清理事件去重表，避免 Frigate event_id 长期堆积。"""
        now = time.monotonic()
        cutoff = now - max(30.0, max_age_sec)
        dead = [k for k, ts in self._recent_events.items() if ts < cutoff]
        for k in dead:
            self._recent_events.pop(k, None)
        # 静音窗口过期后可清
        for cam, until in list(self._silent_until.items()):
            if until < now:
                self._silent_until.pop(cam, None)
                self._miss_streak.pop(cam, None)
        return len(dead)
