"""ESP 辅助感知状态机：只影响唤醒，绝不开门。"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from .models import AlertRecord, EspSenseEvent

_LOGGER = logging.getLogger(__name__)

SensorHealth = Literal["ok", "suppressed", "unavailable"]
EmitAlert = Callable[[AlertRecord], Awaitable[None] | None]
CaptureAssist = Callable[[str, float], Awaitable[dict[str, Any]]]


@dataclass
class SenseRuntime:
    """温湿度与 PIR/按钮武装状态（纯逻辑，不依赖 HA）。"""

    emit_alert: EmitAlert | None = None
    capture_assist: CaptureAssist | None = None
    pir_assist_enabled: bool = True
    button_assist_enabled: bool = True
    assist_seconds: float = 8.0
    button_cooldown_sec: float = 3.0
    pir_cooldown_sec: float = 2.0
    long_press_sec: float = 8.0
    pir_stuck_sec: float = 600.0
    telemetry_stale_sec: float = 90.0
    dht_drop_limit: int = 5
    pir_period_need: int = 6
    pir_period_jitter: float = 0.2

    temperature_c: float | None = None
    humidity_pct: float | None = None
    last_telemetry_ts: float = 0.0
    dht_health: SensorHealth = "unavailable"
    pir_health: SensorHealth = "ok"
    button_health: SensorHealth = "ok"
    last_alert: AlertRecord | None = None

    _seen_ids: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    _dht_drops: int = 0
    _last_btn_assist: float = 0.0
    _last_pir_assist: float = 0.0
    _btn_down_since: float | None = None
    _pir_high_since: float | None = None
    _pir_rise_times: deque[float] = field(default_factory=lambda: deque(maxlen=12))
    _alerts: dict[str, AlertRecord] = field(default_factory=dict)
    door_open_calls: int = 0  # 测试用：本模块永不 ++

    def status(self) -> dict[str, Any]:
        return {
            "temperature_c": self.temperature_c,
            "humidity_pct": self.humidity_pct,
            "dht_health": self.dht_health,
            "pir_health": self.pir_health,
            "button_health": self.button_health,
            "pir_assist_enabled": self.pir_assist_enabled,
            "button_assist_enabled": self.button_assist_enabled,
            "last_alert": self.last_alert.model_dump(by_alias=True) if self.last_alert else None,
            "telemetry_age_sec": (time.time() - self.last_telemetry_ts) if self.last_telemetry_ts else None,
        }

    async def handle(self, event: EspSenseEvent, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        if event.event_id in self._seen_ids:
            return {"ok": True, "action": "dup_drop"}
        self._seen_ids.append(event.event_id)

        if abs(now - event.ts) > 60:
            # 单次偏差丢弃；连续偏差由外部 health 循环告警
            return {"ok": True, "action": "skew_drop"}

        if event.kind == "telemetry":
            return await self._on_telemetry(event, now)
        if event.kind == "pir":
            return await self._on_pir(event, now)
        if event.kind == "button":
            return await self._on_button(event, now)
        return {"ok": False, "action": "unknown_kind"}

    async def _emit(
        self,
        *,
        code: str,
        severity: Literal["warning", "critical"],
        sensor: str,
        summary: str,
        state: Literal["open", "suppressed", "acked", "ignored", "recovered"] = "suppressed",
        detail: dict[str, Any] | None = None,
    ) -> AlertRecord:
        alert = AlertRecord(
            alert_id=str(uuid.uuid4()),
            code=code,
            severity=severity,
            sensor=sensor,
            summary=summary,
            state=state,
            handled_by="center",
            detail=detail or {},
            ts=time.time(),
        )
        self._alerts[alert.alert_id] = alert
        self.last_alert = alert
        if self.emit_alert:
            maybe = self.emit_alert(alert)
            if maybe is not None:
                await maybe
        return alert

    async def _on_telemetry(self, event: EspSenseEvent, now: float) -> dict[str, Any]:
        t = event.temperature_c
        h = event.humidity_pct
        if t is None or h is None:
            self._dht_drops += 1
            if self._dht_drops >= self.dht_drop_limit:
                self.dht_health = "unavailable"
                self.temperature_c = None
                self.humidity_pct = None
                await self._emit(
                    code="dht_unavailable",
                    severity="warning",
                    sensor="dht",
                    summary="温湿度连续丢弃，实体不可用",
                )
            return {"ok": True, "action": "dht_drop"}

        if t < -10 or t > 60 or h < 0 or h > 100:
            self._dht_drops += 1
            return {"ok": True, "action": "dht_oob"}

        if self.temperature_c is not None and abs(t - self.temperature_c) > 15:
            self._dht_drops += 1
            return {"ok": True, "action": "dht_jump"}
        if self.humidity_pct is not None and abs(h - self.humidity_pct) > 30:
            self._dht_drops += 1
            return {"ok": True, "action": "dht_jump"}

        self._dht_drops = 0
        self.temperature_c = t
        self.humidity_pct = h
        self.last_telemetry_ts = now
        self.dht_health = "ok"
        return {"ok": True, "action": "telemetry_ok"}

    async def _on_pir(self, event: EspSenseEvent, now: float) -> dict[str, Any]:
        edge = (event.edge or "").lower()
        # 周期误报用事件时间戳，避免本机 now 挤在同一毫秒
        event_ts = float(event.ts or now)
        if edge == "rise":
            self._pir_high_since = event_ts
            self._pir_rise_times.append(event_ts)
            if self._periodic_false_alarm():
                self.pir_health = "suppressed"
                await self._emit(
                    code="pir_periodic",
                    severity="warning",
                    sensor="pir",
                    summary="人体红外近似周期触发，已停止用其唤醒（疑似日光/热源）",
                )
                await self._maybe_combo_alert()
                return {"ok": True, "action": "pir_suppressed_periodic"}
        elif edge == "fall":
            self._pir_high_since = None

        if self._pir_high_since and now - self._pir_high_since >= self.pir_stuck_sec:
            self.pir_health = "suppressed"
            await self._emit(
                code="pir_stuck",
                severity="warning",
                sensor="pir",
                summary="人体红外高电平过久，已停止用其唤醒",
            )
            await self._maybe_combo_alert()
            return {"ok": True, "action": "pir_suppressed_stuck"}

        if self.pir_health != "ok" or not self.pir_assist_enabled:
            return {"ok": True, "action": "pir_ignored"}

        if edge != "rise":
            return {"ok": True, "action": "pir_edge_ignore"}

        if now - self._last_pir_assist < self.pir_cooldown_sec:
            return {"ok": True, "action": "pir_cooldown"}

        self._last_pir_assist = now
        frames = await self._assist("pir")
        if frames == 0:
            await self._emit(
                code="pir_no_frames",
                severity="warning",
                sensor="pir",
                summary="红外唤醒时摄像头无画面，未改门策略",
                state="open",
            )
        return {"ok": True, "action": "pir_assist", "frames": frames}

    async def _on_button(self, event: EspSenseEvent, now: float) -> dict[str, Any]:
        edge = (event.edge or "").lower()
        if edge == "press":
            self._btn_down_since = now
            if self.button_health != "ok" or not self.button_assist_enabled:
                return {"ok": True, "action": "button_ignored"}
            if now - self._last_btn_assist < self.button_cooldown_sec:
                return {"ok": True, "action": "button_cooldown"}
            self._last_btn_assist = now
            frames = await self._assist("button")
            return {"ok": True, "action": "button_assist", "frames": frames}

        if edge == "release":
            held = (now - self._btn_down_since) if self._btn_down_since else 0.0
            self._btn_down_since = None
            if held >= self.long_press_sec or self.button_health == "suppressed":
                # 松开后重新武装
                was = self.button_health
                self.button_health = "ok"
                if was == "suppressed":
                    await self._emit(
                        code="button_rearmed",
                        severity="warning",
                        sensor="button",
                        summary="按钮已松开，辅助唤醒重新武装",
                        state="recovered",
                    )
            return {"ok": True, "action": "button_release", "held": held}

        return {"ok": True, "action": "button_edge_ignore"}

    async def tick(self, *, now: float | None = None) -> None:
        """周期检查：长按、telemetry 过期、组合异常。"""
        now = time.time() if now is None else now
        if self._btn_down_since and now - self._btn_down_since >= self.long_press_sec:
            if self.button_health != "suppressed":
                self.button_health = "suppressed"
                await self._emit(
                    code="button_long_press",
                    severity="warning",
                    sensor="button",
                    summary="按钮长按/卡住，已停止用其唤醒",
                )
                await self._maybe_combo_alert()

        if self.last_telemetry_ts and now - self.last_telemetry_ts > self.telemetry_stale_sec:
            if self.dht_health != "unavailable":
                self.dht_health = "unavailable"
                self.temperature_c = None
                self.humidity_pct = None
                await self._emit(
                    code="dht_stale",
                    severity="warning",
                    sensor="dht",
                    summary="温湿度上报超时，实体不可用",
                )

    def apply_admin_ack(self, alert_id: str, state: str) -> bool:
        alert = self._alerts.get(alert_id)
        if not alert:
            # 仍记录最近一条若匹配
            if self.last_alert and self.last_alert.alert_id == alert_id:
                alert = self.last_alert
            else:
                return False
        alert.state = state  # type: ignore[assignment]
        alert.handled_by = "admin"
        self.last_alert = alert
        return True

    def reenable_sensor(self, sensor: str) -> None:
        if sensor == "pir":
            self.pir_health = "ok"
            self._pir_rise_times.clear()
        elif sensor == "button":
            self.button_health = "ok"
            self._btn_down_since = None
        elif sensor == "dht":
            self.dht_health = "ok"
            self._dht_drops = 0

    def note_unexpected_pulse(self, command_id: str | None) -> None:
        """health 显示 pulsing 但 command_id 不是总控发出的。"""
        # 异步入口由调用方 await _emit — 提供同步包装用 create task 不方便；返回 alert 构造
        pass

    async def alert_unexpected_pulse(self, command_id: str | None) -> AlertRecord:
        return await self._emit(
            code="door_unexpected_pulse",
            severity="critical",
            sensor="door",
            summary="ESP 显示正在吸合，但无匹配的总控命令号",
            state="open",
            detail={"command_id": command_id or ""},
        )

    def _periodic_false_alarm(self) -> bool:
        times = list(self._pir_rise_times)
        if len(times) < self.pir_period_need:
            return False
        intervals = [times[i] - times[i - 1] for i in range(1, len(times))]
        if any(x <= 0.05 for x in intervals):
            return False
        mean = sum(intervals) / len(intervals)
        if mean <= 0:
            return False
        return all(abs(x - mean) / mean <= self.pir_period_jitter for x in intervals)

    async def _maybe_combo_alert(self) -> None:
        if self.pir_health == "suppressed" and self.button_health == "suppressed":
            await self._emit(
                code="assist_untrusted",
                severity="warning",
                sensor="assist",
                summary="门口辅助感知不可信（按钮与红外均异常），人脸循环继续",
                state="suppressed",
            )

    async def _assist(self, source: str) -> int:
        if not self.capture_assist:
            return -1
        try:
            result = await self.capture_assist(source, self.assist_seconds)
            return int(result.get("frames", -1))
        except Exception:
            _LOGGER.exception("认证捕捉失败 source=%s", source)
            return -1
