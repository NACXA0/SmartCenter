from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.face.embedder import MockEmbedder, cosine
from app.face.match import DoorMatcher, MatchConfig
from app.face.quality import QualityConfig, evaluate_meta
from app.face.session import SessionManager
from app.store import GalleryStore


@pytest.fixture()
def store(tmp_path: Path) -> GalleryStore:
    return GalleryStore(tmp_path / "t.sqlite3")


def test_quality_rejects_gray():
    ok, reason = evaluate_meta({"ok": True, "det_score": 0.9, "box_w": 100, "box_h": 100, "landmarks": 5, "blur": 0.1, "yaw": 0, "is_gray": True})
    assert not ok and reason == "infrared_or_gray"


def test_quality_ok():
    ok, reason = evaluate_meta({"ok": True, "det_score": 0.9, "box_w": 100, "box_h": 100, "landmarks": 5, "blur": 0.1, "yaw": 0, "is_gray": False})
    assert ok and reason == "ok"


def test_enroll_session_and_static_reject(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    emb.force_meta({"identity_key": "u1", "ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False})
    sm = SessionManager(store, emb, tmp_path / "frames", needed=3, quality=QualityConfig(max_static_cosine=0.99))
    sess = sm.start("1", "甲", "staff", "admin")
    # 同 identity 同图 → 第二帧会被 static 拒绝
    from PIL import Image
    import io

    def jpeg_bytes(seed: int) -> bytes:
        arr = np.zeros((160, 160, 3), dtype=np.uint8)
        arr[:] = (seed, 80, 40)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG")
        return buf.getvalue()

    r1 = sm.push_jpeg(sess.session_id, jpeg_bytes(10))
    assert r1["ok"] and not r1["done"]
    r2 = sm.push_jpeg(sess.session_id, jpeg_bytes(10))
    assert not r2["ok"] and r2["reason"] == "static_photo"

    # 换种子产生不同向量
    emb.force_meta({"identity_key": "u1-a", "ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False})
    assert sm.push_jpeg(sess.session_id, jpeg_bytes(20))["ok"]
    emb.force_meta({"identity_key": "u1-b", "ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False})
    r3 = sm.push_jpeg(sess.session_id, jpeg_bytes(30))
    assert r3["done"] and r3["face_status"] == "accepted"
    p = store.get_person("1")
    assert p and p.face_status == "accepted"


def _enroll(store: GalleryStore, emb: MockEmbedder, tmp: Path, uid: str, key: str, needed: int = 3) -> None:
    sm = SessionManager(store, emb, tmp / f"f-{uid}", needed=needed)
    sess = sm.start(uid, uid, "staff", "a")
    from PIL import Image
    import io

    for i in range(needed):
        emb.force_meta({"identity_key": f"{key}-{i}", "ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False})
        arr = np.zeros((100, 100, 3), dtype=np.uint8)
        arr[:] = (i * 3 + 10, 50, 70)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG")
        sm.push_jpeg(sess.session_id, buf.getvalue())


def test_match_grant_cooldown_and_duplicate(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "42", "person42")
    # 比对时用同一 identity 前缀保证高相似——简化：直接把内存向量复制给帧嵌入
    matcher = DoorMatcher(
        store,
        emb,
        MatchConfig(
            match_threshold=0.2,
            verify_threshold=0.9,
            cooldown_sec=30,
            required_match_frames=3,
            door_cameras=["front_desk"],
            door_zones=["z1"],
        ),
    )
    mem = store.memory_vectors()["42"][0]

    class Fixed(MockEmbedder):
        def embed(self, image_bgr):
            meta = {"ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False}
            return mem, meta

    matcher.embedder = Fixed()
    frames = [np.zeros((80, 80, 3), dtype=np.uint8) for _ in range(3)]
    for f in frames:
        f[..., 0] = 30
        f[..., 1] = 80
        f[..., 2] = 160
    ok, _ = matcher.should_handle("front_desk", ["z1"], "e1")
    assert ok
    r = matcher.match_frames("front_desk", frames, event_id="e1")
    assert r.decision == "grant" and r.grant and r.user_id == "42"
    # 冷却
    r2 = matcher.match_frames("front_desk", frames, event_id="e2")
    assert r2.decision == "skip" and r2.reason == "cooldown"
    # 冷却落盘：新 matcher 同 store 仍冷却
    m2 = DoorMatcher(store, matcher.embedder, matcher.cfg)
    assert store.cooldown_active("42", time.monotonic())
    r3 = m2.match_frames("front_desk", frames, event_id="e3")
    assert r3.decision == "skip"


def test_multi_identity_deny(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "1", "a")
    _enroll(store, emb, tmp_path, "2", "b")
    v1 = store.memory_vectors()["1"][0]
    v2 = store.memory_vectors()["2"][0]
    matcher = DoorMatcher(
        store,
        emb,
        MatchConfig(match_threshold=0.2, required_match_frames=3, door_cameras=["c"], door_zones=[]),
    )
    seq = [v1, v2, v1]

    class Alt(MockEmbedder):
        def __init__(self):
            super().__init__()
            self.i = 0

        def embed(self, image_bgr):
            meta = {"ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False}
            v = seq[self.i % len(seq)]
            self.i += 1
            return v, meta

    matcher.embedder = Alt()
    frames = [np.zeros((60, 60, 3), dtype=np.uint8) for _ in range(3)]
    for f in frames:
        f[..., 0], f[..., 1], f[..., 2] = 10, 90, 200
    r = matcher.match_frames("c", frames)
    assert r.decision == "deny" and r.reason == "multi_identity"


def test_model_not_loaded_denies(store: GalleryStore):
    emb = MockEmbedder()
    emb.ready = False
    matcher = DoorMatcher(store, emb, MatchConfig(door_cameras=["c"]))
    r = matcher.match_frames("c", [np.zeros((40, 40, 3), dtype=np.uint8)])
    assert r.decision == "deny" and r.reason == "model_not_loaded"


def test_disable_removes_from_memory(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "9", "x")
    assert "9" in store.memory_vectors()
    store.set_enabled("9", False)
    assert "9" not in store.memory_vectors()


def test_online_backup(store: GalleryStore, tmp_path: Path):
    store.upsert_person("1", "a", "accepted")
    dest = store.online_backup(tmp_path / "bak.sqlite3")
    assert dest.is_file() and dest.stat().st_size > 0


def test_verify_path(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "7", "p7")
    st = store.bump_verify("7", True, need=3)
    assert st == "accepted"
    store.bump_verify("7", True, need=3)
    st = store.bump_verify("7", True, need=3)
    assert st == "verified"
    # fail streak
    store.set_status("7", "accepted")
    store._conn.execute("UPDATE persons SET verify_ok_count=0, verify_fail_streak=0 WHERE user_id='7'")
    store._conn.commit()
    store.bump_verify("7", False, need=3)
    store.bump_verify("7", False, need=3)
    st = store.bump_verify("7", False, need=3)
    assert st == "pending"


def test_infrared_skip(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "3", "g")
    matcher = DoorMatcher(store, emb, MatchConfig(match_threshold=0.2, required_match_frames=1, door_cameras=["c"]))
    gray = np.full((60, 60, 3), 40, dtype=np.uint8)
    r = matcher.match_frames("c", [gray])
    assert r.decision == "skip" and r.reason == "infrared_or_gray"


def test_event_dedup(store: GalleryStore):
    emb = MockEmbedder()
    matcher = DoorMatcher(store, emb, MatchConfig(door_cameras=["front_desk"], door_zones=["z1"]))
    ok1, _ = matcher.should_handle("front_desk", ["z1"], "same")
    assert ok1
    matcher._recent_events["front_desk:same"] = time.monotonic()
    ok2, why = matcher.should_handle("front_desk", ["z1"], "same")
    assert not ok2 and why == "dedup"


def test_duplicate_command_id(store: GalleryStore):
    assert store.mark_grant("abc")
    assert not store.mark_grant("abc")


def test_session_user_mismatch(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    emb.force_meta({"identity_key": "u", "ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False})
    sm = SessionManager(store, emb, tmp_path / "f", needed=5)
    sess = sm.start("10", "x", "student", "relay")
    from PIL import Image
    import io

    arr = np.zeros((80, 80, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG")
    r = sm.push_jpeg(sess.session_id, buf.getvalue(), expected_user_id="99")
    assert not r["ok"] and r["reason"] == "user_mismatch"


def test_cooldown_survives_store_reopen(tmp_path: Path):
    db = tmp_path / "c.sqlite3"
    store = GalleryStore(db)
    until_wall = time.time() + 30
    store.set_cooldown("u", time.monotonic() + 30, until_wall)
    store.close()
    store2 = GalleryStore(db)
    assert store2.cooldown_active("u", time.monotonic())


def test_disable_clears_grant_path(store: GalleryStore, tmp_path: Path):
    emb = MockEmbedder()
    _enroll(store, emb, tmp_path, "5", "d5")
    store.set_enabled("5", False)
    store.clear_cooldown("5")
    mem = store.memory_vectors().get("5")
    assert not mem
    matcher = DoorMatcher(store, emb, MatchConfig(match_threshold=0.01, required_match_frames=1, door_cameras=["c"]))

    class Fixed(MockEmbedder):
        def embed(self, image_bgr):
            # 即使向量碰巧高分，人已停用
            v = np.ones(8, dtype=np.float32)
            meta = {"ok": True, "det_score": 0.99, "box_w": 120, "box_h": 120, "landmarks": 5, "blur": 0.05, "yaw": 0, "is_gray": False}
            return v, meta

    matcher.embedder = Fixed()
    color = np.zeros((40, 40, 3), dtype=np.uint8)
    color[..., 0], color[..., 1], color[..., 2] = 20, 100, 180
    r = matcher.match_frames("c", [color])
    assert r.decision == "deny"
