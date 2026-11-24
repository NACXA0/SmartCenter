"""企业微信通知：可降级，永不阻塞开门。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

_LOGGER = logging.getLogger(__name__)


@dataclass
class WeComNotifier:
    webhook: str = ""
    max_backlog: int = 200
    drop_after_sec: float = 7200
    fail_threshold: int = 5
    open_sec: float = 60
    _queue: deque = field(default_factory=deque)
    _fails: int = 0
    _open_until: float = 0
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

    def submit(self, text: str, *, level: str = "warning") -> None:
        if not self.webhook:
            return
        self._queue.append({"ts": time.time(), "text": text, "level": level})
        while len(self._queue) > self.max_backlog:
            self._queue.popleft()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._drain_once()
            except Exception:
                _LOGGER.exception("通知循环异常")
            await asyncio.sleep(1)

    async def _drain_once(self) -> None:
        now = time.time()
        if now < self._open_until:
            return
        while self._queue:
            item = self._queue[0]
            if item["level"] != "critical" and now - item["ts"] > self.drop_after_sec:
                self._queue.popleft()
                continue
            ok = await self._send(item["text"])
            if ok:
                self._queue.popleft()
                self._fails = 0
            else:
                self._fails += 1
                if self._fails >= self.fail_threshold:
                    self._open_until = time.time() + self.open_sec
                    _LOGGER.warning("企业微信熔断 %ss", self.open_sec)
                break

    async def _send(self, text: str) -> bool:
        if not self.webhook:
            return True
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    self.webhook,
                    json={"msgtype": "text", "text": {"content": text[:2000]}},
                )
            return resp.status_code < 300
        except httpx.HTTPError as exc:
            _LOGGER.warning("企业微信发送失败: %s", exc)
            return False
