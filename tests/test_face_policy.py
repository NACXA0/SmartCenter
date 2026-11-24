import time

import pytest

from lobn_office.audit import AuditLog
from lobn_office.door import DoorController, MockDoorAdapter
from lobn_office.hot_path import InMemoryHotPath
from lobn_office.models import CctvEvent, Grant, PersonRecord
from lobn_office.notify import WeComNotifier
from lobn_office.policy import AccessPolicy


@pytest.fixture
def policy(tmp_path):
    adapter = MockDoorAdapter()
    door = DoorController(adapter=adapter, face_cooldown_sec=0, grant_cooldown_sec=0)
    hot = InMemoryHotPath()
    pol = AccessPolicy(
        door=door,
        hot=hot,
        notify=WeComNotifier(""),
        audit=AuditLog(tmp_path),
        face_auto_open=True,
        require_grant_for_face=True,
    )
    return pol, hot, door, adapter


@pytest.mark.asyncio
async def test_face_without_grant_recorded_but_denied(policy):
    pol, hot, door, adapter = policy
    await door.startup_lock()
    hot.upsert_person(PersonRecord(person_id=1, user_id="u1", name="张三"))
    event = CctvEvent(
        type="face_known",
        cam_id="door1",
        ts=time.time(),
        payload={"person_id": 1, "similarity": 0.9},
    )
    result = await pol.on_cctv_event(event)
    assert result["action"] == "denied"
    assert "授权" in result["reason"]
    assert not [c for c in adapter.calls if c["action"] == "open"]
    sightings = [r for r in pol.audit.recent(20) if r.get("action") == "face_sighting"]
    assert sightings
    assert sightings[-1]["authorized"] is False


@pytest.mark.asyncio
async def test_face_with_grant_opens(policy):
    pol, hot, door, adapter = policy
    await door.startup_lock()
    now = time.time()
    hot.upsert_person(PersonRecord(person_id=1, user_id="u1", name="张三"))
    hot.upsert_grant(
        Grant(
            grant_id="g1",
            user_id="u1",
            window_start=now - 10,
            window_end=now + 100,
            status="pending",
        )
    )
    event = CctvEvent(
        type="face_known",
        cam_id="door1",
        ts=now,
        payload={"person_id": 1, "similarity": 0.92},
    )
    result = await pol.on_cctv_event(event)
    assert result["action"] == "opened"
    assert any(c["action"] == "open" for c in adapter.calls)


@pytest.mark.asyncio
async def test_unknown_coalesced(policy):
    pol, hot, door, adapter = policy
    event = CctvEvent(type="face_unknown", cam_id="door1", ts=time.time(), payload={"similarity": 0.1})
    r1 = await pol.on_cctv_event(event)
    r2 = await pol.on_cctv_event(event)
    assert r1["action"] == "recorded"
    assert r2["action"] == "unknown_coalesced"
