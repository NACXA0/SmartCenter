"""EspDoorAdapter 与固件脉冲规则。"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from lobn_office.door import DoorController, EspDoorAdapter

HOST_SIM = Path(__file__).resolve().parents[2] / "firmware" / "esp32s3_door" / "host_sim"
sys.path.insert(0, str(HOST_SIM))
from door_logic import DoorPulseSim, clamp_seconds, is_dht_garbage  # noqa: E402


def test_clamp_seconds():
    assert clamp_seconds(0.05) == 0.2
    assert clamp_seconds(20) == 15.0
    assert clamp_seconds(5) == 5.0


def test_busy_rejects_second_pulse():
    sim = DoorPulseSim()
    code, body = sim.open("c1", 5)
    assert code == 200 and body["result"] == "pulsed"
    code2, _ = sim.open("c2", 5)
    assert code2 == 409
    sim.tick_release()
    code3, body3 = sim.open("c3", 5)
    assert code3 == 200 and body3["command_id"] == "c3"


def test_dht_garbage():
    assert is_dht_garbage(85.0, 0.0)
    assert is_dht_garbage(100, 50)
    assert not is_dht_garbage(24.0, 55.0)


@pytest.mark.asyncio
async def test_esp_adapter_pulsed_ok(monkeypatch):
    calls: list[str] = []

    class FakeResp:
        status_code = 200
        content = b'{"result":"pulsed","command_id":"cid-1"}'

        def json(self):
            return {"result": "pulsed", "command_id": "cid-1"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            calls.append(url)
            return FakeResp()

        async def get(self, url, **kwargs):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    adapter = EspDoorAdapter(base_url="http://esp.local:8080", token="tok")
    door = DoorController(adapter=adapter, grant_cooldown_sec=0, face_cooldown_sec=0)
    await door.startup_lock()
    result, cid = await door.open(reason="manual", command_id="cid-1")
    assert result == "opened"
    assert cid == "cid-1"
    assert adapter.last_command_id == "cid-1"
    assert any("/v1/door/command" in u for u in calls)


@pytest.mark.asyncio
async def test_esp_timeout_unknown_no_second_pulse(monkeypatch):
    posts = {"n": 0}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            posts["n"] += 1
            raise httpx.ConnectTimeout("boom")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    adapter = EspDoorAdapter(base_url="http://esp.local:8080", token="tok", timeout_sec=0.5)
    door = DoorController(adapter=adapter, grant_cooldown_sec=0, face_cooldown_sec=0)
    door._ready = True
    result, cid = await door.open(reason="manual", command_id="cid-x")
    assert result == "unknown"
    assert cid == "cid-x"
    assert adapter.offline is True
    assert posts["n"] == 1
