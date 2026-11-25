"""告警：本地审计 + 企业微信 + 异步推云端；不阻塞开门。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .models import AlertRecord

if TYPE_CHECKING:
    from .audit import AuditLog
    from .cloud_client import CloudClient
    from .notify import WeComNotifier
    from .sense import SenseRuntime

_LOGGER = logging.getLogger(__name__)


@dataclass
class AlertHub:
    audit: AuditLog
    notify: WeComNotifier
    cloud: CloudClient
    sense: SenseRuntime
    _queue: deque[AlertRecord] = field(default_factory=deque)
    _by_id: dict[str, AlertRecord] = field(default_factory=dict)
    _task: asyncio.Task | None = None
    _running: bool = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def publish(self, alert: AlertRecord) -> None:
        self._by_id[alert.alert_id] = alert
        self.sense.last_alert = alert
        self.audit.append(
            "sensor_alert",
            alert_id=alert.alert_id,
            code=alert.code,
            severity=alert.severity,
            state=alert.state,
            summary=alert.summary,
            sensor=alert.sensor,
        )
        self.notify.submit(
            f"[{alert.severity}] {alert.summary} ({alert.code})",
            level=alert.severity,
        )
        self._queue.append(alert)

    async def _loop(self) -> None:
        while self._running:
            try:
                while self._queue:
                    alert = self._queue[0]
                    ok = await self.cloud.push_alert(alert)
                    if ok:
                        self._queue.popleft()
                    else:
                        break
                # 拉回店员确认
                items = await self.cloud.pull_alert_acks()
                for item in items:
                    aid = str(item.get("alert_id") or "")
                    state = str(item.get("state") or "")
                    if not aid or state not in ("acked", "ignored", "recovered"):
                        continue
                    self.sense.apply_admin_ack(aid, state)
                    local = self._by_id.get(aid)
                    if local:
                        local.state = state  # type: ignore[assignment]
                        local.handled_by = "admin"
                    reenable = item.get("reenable_sensor")
                    if reenable:
                        self.sense.reenable_sensor(str(reenable))
                    await self.cloud.ack_alert_pulled(aid)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("告警同步循环异常")
            await asyncio.sleep(5)

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        rows = list(self._by_id.values())[-n:]
        return [r.model_dump(by_alias=True) for r in rows]
