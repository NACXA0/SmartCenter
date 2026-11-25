"""传感器状态机：误报抑制且绝不开门。"""

from __future__ import annotations

import time

import pytest

from lobn_office.models import AlertRecord, EspSenseEvent
from lobn_office.sense import SenseRuntime


def _ev(kind: str, *, edge: str = "", eid: str = "e1", ts: float | None = None, t=None, h=None):
    return EspSenseEvent(
        event_id=eid,
        kind=kind,  # type: ignore[arg-type]
        edge=edge,
        temperature_c=t,
        humidity_pct=h,
        ts=time.time() if ts is None else ts,
    )


@pytest.mark.asyncio
async def test_pir_and_button_never_open_door():
    opens = {"n": 0}

    async def capture(source, seconds):
        return {"frames": 1}

    sense = SenseRuntime(capture_assist=capture)
    # 若误接开门，测试用计数器应保持 0
    r = await sense.handle(_ev("pir", edge="rise", eid="p1"))
    assert r["action"] == "pir_assist"
    r2 = await sense.handle(_ev("button", edge="press", eid="b1"))
    assert r2["action"] == "button_assist"
    assert sense.door_open_calls == 0
    assert opens["n"] == 0


@pytest.mark.asyncio
async def test_pir_periodic_suppresses():
    alerts: list[AlertRecord] = []

    async def emit(a: AlertRecord):
        alerts.append(a)

    sense = SenseRuntime(emit_alert=emit, pir_period_need=6, capture_assist=lambda s, sec: _ok())
    base = time.time()
    for i in range(6):
        await sense.handle(_ev("pir", edge="rise", eid=f"p{i}", ts=base + i * 10.0))
    assert sense.pir_health == "suppressed"
    assert any(a.code == "pir_periodic" for a in alerts)
    # 抑制后不再 assist（时间戳仍在 ±60s 窗内）
    r = await sense.handle(_ev("pir", edge="rise", eid="p99", ts=time.time()))
    assert r["action"] == "pir_ignored"


async def _ok():
    return {"frames": 1}


@pytest.mark.asyncio
async def test_button_long_press_suppress():
    alerts: list[AlertRecord] = []

    async def emit(a: AlertRecord):
        alerts.append(a)

    sense = SenseRuntime(emit_alert=emit, long_press_sec=8, capture_assist=lambda s, sec: _ok())
    t0 = time.time()
    await sense.handle(_ev("button", edge="press", eid="bp", ts=t0))
    await sense.tick(now=t0 + 9)
    assert sense.button_health == "suppressed"
    assert any(a.code == "button_long_press" for a in alerts)


@pytest.mark.asyncio
async def test_dht_oob_no_update():
    sense = SenseRuntime()
    await sense.handle(_ev("telemetry", eid="t1", t=24.0, h=50.0))
    assert sense.temperature_c == 24.0
    await sense.handle(_ev("telemetry", eid="t2", t=90.0, h=50.0))
    assert sense.temperature_c == 24.0  # 越界丢弃


@pytest.mark.asyncio
async def test_unexpected_pulse_critical():
    alerts: list[AlertRecord] = []

    async def emit(a: AlertRecord):
        alerts.append(a)

    sense = SenseRuntime(emit_alert=emit)
    a = await sense.alert_unexpected_pulse("")
    assert a.severity == "critical"
    assert a.code == "door_unexpected_pulse"


@pytest.mark.asyncio
async def test_dup_event_drop():
    sense = SenseRuntime(capture_assist=lambda s, sec: _ok())
    await sense.handle(_ev("button", edge="press", eid="same"))
    r = await sense.handle(_ev("button", edge="press", eid="same"))
    assert r["action"] == "dup_drop"
