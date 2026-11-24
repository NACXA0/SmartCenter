import asyncio

import pytest

from lobn_office.door import DoorController, MockDoorAdapter


@pytest.mark.asyncio
async def test_timeout_unknown_no_second_pulse():
    adapter = MockDoorAdapter()
    adapter.fail_next = True
    door = DoorController(adapter=adapter, grant_cooldown_sec=0, face_cooldown_sec=0)
    await door.startup_lock()
    result, cid = await door.open(reason="manual")
    assert result == "unknown"
    assert cid
    assert len([c for c in adapter.calls if c["action"] == "open"]) == 1


@pytest.mark.asyncio
async def test_not_ready_denied():
    door = DoorController(adapter=MockDoorAdapter())
    result, cid = await door.open(reason="manual")
    assert result == "denied"
    assert cid == ""


@pytest.mark.asyncio
async def test_cooldown():
    adapter = MockDoorAdapter()
    door = DoorController(adapter=adapter, face_cooldown_sec=60)
    await door.startup_lock()
    r1, _ = await door.open(reason="face_match", person_id=1)
    r2, _ = await door.open(reason="face_match", person_id=1)
    assert r1 == "opened"
    assert r2 == "denied"
