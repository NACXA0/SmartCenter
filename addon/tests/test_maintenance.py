from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from app.config import Settings
from app.face.embedder import MockEmbedder
from app.face.match import DoorMatcher, MatchConfig
from app.face.session import SessionManager
from app.logging_setup import setup_logging
from app.maintenance import prune_orphan_frames, run_maintenance_once
from app.store import GalleryStore


def test_audit_and_grants_prune(tmp_path: Path):
    store = GalleryStore(tmp_path / "t.sqlite3")
    for i in range(20):
        store.audit("1", "cam", 0.5, "deny" if i % 2 else "grant", {"i": i})
        store.mark_grant(f"cmd-{i}")
    store._conn.execute("UPDATE grants_seen SET created_at=?", (time.time() - 100 * 3600,))
    store._conn.commit()

    a = store.prune_audit(max_rows=5, max_age_days=365)
    assert a["remaining"] == 5
    assert a["deleted"] >= 15
    g = store.prune_grants_seen(max_age_hours=24)
    assert g == 20
    st = store.stats()
    assert st["match_audit"] == 5
    assert st["grants_seen"] == 0


def test_session_expire_drops_partial_frames(tmp_path: Path):
    store = GalleryStore(tmp_path / "t.sqlite3")
    emb = MockEmbedder()
    emb.force_meta(
        {
            "identity_key": "x",
            "ok": True,
            "det_score": 0.99,
            "box_w": 120,
            "box_h": 120,
            "landmarks": 5,
            "blur": 0.05,
            "yaw": 0,
            "is_gray": False,
        }
    )
    frames = tmp_path / "frames"
    sm = SessionManager(store, emb, frames, needed=5)
    sess = sm.start("9", "九", "staff", "a")
    from PIL import Image
    import io

    arr = np.zeros((80, 80, 3), dtype=np.uint8)
    arr[:] = (20, 40, 60)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG")
    assert sm.push_jpeg(sess.session_id, buf.getvalue())["ok"]
    assert list(frames.rglob("*.jpg"))

    sm._sessions[sess.session_id].created_at = time.time() - 9999
    assert sm.expire_stale(ttl_sec=60) == 1
    assert list(frames.rglob("*.jpg")) == []


def test_orphan_frames_and_maintenance(tmp_path: Path):
    store = GalleryStore(tmp_path / "t.sqlite3")
    frames = tmp_path / "enroll_frames"
    frames.mkdir()
    orphan = frames / "ghost" / "x.jpg"
    orphan.parent.mkdir()
    orphan.write_bytes(b"JPEG")
    kept_dir = frames / "1"
    kept_dir.mkdir()
    kept = kept_dir / "keep.jpg"
    kept.write_bytes(b"JPEG")
    store.commit_enrollment(
        "1",
        "一",
        "mock-v1",
        [np.zeros(8, dtype=np.float32)],
        [str(kept.resolve())],
    )
    removed = prune_orphan_frames(store, frames)
    assert removed >= 1
    assert kept.is_file()
    assert not orphan.is_file()

    settings = Settings(data_dir=tmp_path, audit_max_rows=100, session_ttl_sec=60)
    emb = MockEmbedder()
    sm = SessionManager(store, emb, frames, needed=3)
    matcher = DoorMatcher(store, emb, MatchConfig(door_cameras=["front_desk"]))
    matcher._recent_events["old"] = time.monotonic() - 9999
    stats = run_maintenance_once(store, settings, sm, matcher)
    assert stats["audit"]["remaining"] >= 0
    assert matcher._recent_events.get("old") is None or stats["events"] >= 1


def test_logging_rotate_setup(tmp_path: Path):
    import app.logging_setup as ls

    ls._CONFIGURED = False
    path = setup_logging(tmp_path, max_bytes=1024, backup_count=2)
    assert path.parent.is_dir()


def test_dashboard_stats(tmp_path: Path):
    store = GalleryStore(tmp_path / "t.sqlite3")
    store.upsert_person("1", "甲", "pending")
    store.upsert_person("2", "乙", "verified")
    store.audit("2", "front_desk", 0.9, "grant", {})
    store.audit(None, "front_desk", 0.0, "deny", {"reason": "x"})
    d = store.dashboard()
    assert d["persons"]["total"] == 2
    assert d["persons"]["by_status"]["pending"] == 1
    assert d["access"]["h24"]["grant"] >= 1
    assert d["access"]["h24"]["deny"] >= 1
    store.set_display_name("1", "甲改")
    assert store.get_person("1").display_name == "甲改"
