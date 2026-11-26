from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


class MqttBus:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.host = (host or "").strip()
        self.port = port
        self.user = user
        self.password = password
        self._client = None
        self._task: asyncio.Task | None = None
        self._fail_logged = False

    @property
    def enabled(self) -> bool:
        h = self.host.lower()
        return h not in ("", "off", "disabled", "none", "-")

    async def start(self, on_frigate_event: OnEvent) -> None:
        if not self.enabled:
            _LOGGER.info("MQTT disabled (host=%r); 采集/比对 API 仍可用，门口事件需连 Mosquitto", self.host)
            return
        try:
            from aiomqtt import Client
        except ImportError:
            _LOGGER.warning("aiomqtt missing; MQTT disabled")
            return

        async def _run() -> None:
            while True:
                try:
                    async with Client(
                        hostname=self.host,
                        port=self.port,
                        username=self.user or None,
                        password=self.password or None,
                    ) as client:
                        self._client = client
                        self._fail_logged = False
                        await client.subscribe("frigate/events")
                        _LOGGER.info("mqtt subscribed frigate/events @ %s", self.host)
                        async for message in client.messages:
                            try:
                                payload = json.loads(message.payload.decode("utf-8"))
                            except Exception:
                                continue
                            await on_frigate_event(payload)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._client = None
                    if not self._fail_logged:
                        _LOGGER.warning(
                            "mqtt unavailable (%s: %s); will retry every 30s — "
                            "本机开发可设 MQTT_HOST=off",
                            type(e).__name__,
                            e,
                        )
                        self._fail_logged = True
                    await asyncio.sleep(30)

        self._task = asyncio.create_task(_run())

    async def publish_grant(self, grant: dict[str, Any]) -> None:
        if not self.enabled:
            _LOGGER.info("mqtt off; grant not published %s", grant.get("command_id"))
            return
        if not self._client:
            _LOGGER.warning("mqtt not connected; grant dropped %s", grant.get("command_id"))
            return
        await self._client.publish("business/access/grant", json.dumps(grant, ensure_ascii=False).encode("utf-8"))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
