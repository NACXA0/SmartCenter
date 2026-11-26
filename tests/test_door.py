import json

import pytest

from lobn_office.const import SCHEMA_HOME_DOOR_COMMAND
from lobn_office.door import DoorController, MockDoorAdapter, MqttDoorAdapter


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


@pytest.mark.asyncio
async def test_mqtt_adapter_publishes_open_json():
    published: list[dict] = []

    async def publish(*, topic: str, payload: str, qos: int = 1, retain: bool = False) -> None:
        published.append(
            {"topic": topic, "payload": payload, "qos": qos, "retain": retain}
        )

    adapter = MqttDoorAdapter(
        publish=publish,
        gate_node="front_gate",
        inner_node="classroom_1",
    )
    adapter.select_target("gate")
    ok = await adapter.open(5, "cmd-1")
    assert ok is True
    assert len(published) == 1
    assert published[0]["topic"] == "home/front_gate/door/command"
    assert published[0]["qos"] == 1
    body = json.loads(published[0]["payload"])
    assert body["schema"] == SCHEMA_HOME_DOOR_COMMAND
    assert body["action"] == "OPEN"
    assert body["ttl_sec"] == 5
    assert body["command_id"] == "cmd-1"


@pytest.mark.asyncio
async def test_mqtt_adapter_inner_target_and_ttl_clamp():
    published: list[dict] = []

    async def publish(*, topic: str, payload: str, qos: int = 1, retain: bool = False) -> None:
        published.append({"topic": topic, "payload": payload})

    adapter = MqttDoorAdapter(
        publish=publish,
        gate_node="front_gate",
        inner_node="classroom_1",
    )
    assert adapter.select_target("inner") == "classroom_1"
    ok = await adapter.open(99, "cmd-inner")
    assert ok is True
    assert published[0]["topic"] == "home/classroom_1/door/command"
    body = json.loads(published[0]["payload"])
    assert body["ttl_sec"] == 10


@pytest.mark.asyncio
async def test_mqtt_adapter_publish_failure_unknown():
    async def publish(*, topic: str, payload: str, qos: int = 1, retain: bool = False) -> None:
        raise RuntimeError("broker down")

    adapter = MqttDoorAdapter(publish=publish)
    door = DoorController(adapter=adapter, grant_cooldown_sec=0, face_cooldown_sec=0)
    await door.startup_lock()
    result, cid = await door.open(reason="manual")
    assert result == "unknown"
    assert cid
    assert adapter.offline is True
