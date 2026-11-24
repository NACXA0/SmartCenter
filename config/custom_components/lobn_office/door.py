"""门禁执行：办公室唯一软件开门口。超时标 unknown，不连发。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import httpx

from .models import DoorCommand

_LOGGER = logging.getLogger(__name__)

DoorResult = Literal["opened", "unknown", "denied"]


class DoorAdapter(ABC):
    @abstractmethod
    async def open(self, seconds: float, command_id: str) -> bool: ...

    @abstractmethod
    async def close(self) -> bool: ...

    @abstractmethod
    async def state(self) -> str: ...


class MockDoorAdapter(DoorAdapter):
    def __init__(self) -> None:
        self._open_until = 0.0
        self.calls: list[dict] = []
        self.fail_next = False

    async def open(self, seconds: float, command_id: str) -> bool:
        self.calls.append({"action": "open", "seconds": seconds, "command_id": command_id, "ts": time.time()})
        if self.fail_next:
            self.fail_next = False
            return False
        self._open_until = time.time() + seconds
        return True

    async def close(self) -> bool:
        self._open_until = 0
        self.calls.append({"action": "close", "ts": time.time()})
        return True

    async def state(self) -> str:
        return "open" if time.time() < self._open_until else "closed"


class HttpRelayAdapter(DoorAdapter):
    def __init__(
        self,
        open_url: str,
        close_url: str = "",
        method: str = "GET",
        timeout_sec: float = 3,
    ) -> None:
        self.open_url = open_url
        self.close_url = close_url
        self.method = method.upper()
        self.timeout_sec = timeout_sec

    async def open(self, seconds: float, command_id: str) -> bool:
        url = self.open_url.replace("{seconds}", str(int(seconds))).replace("{command_id}", command_id)
        return await self._hit(url)

    async def close(self) -> bool:
        if not self.close_url:
            return True
        return await self._hit(self.close_url)

    async def state(self) -> str:
        return "unknown"

    async def _hit(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                if self.method == "POST":
                    resp = await client.post(url)
                else:
                    resp = await client.get(url)
            return resp.status_code < 300
        except httpx.HTTPError as exc:
            _LOGGER.warning("门禁 HTTP 失败: %s", exc)
            return False


@dataclass
class DoorController:
    adapter: DoorAdapter
    door_id: str = "main"
    open_seconds: float = 5
    face_cooldown_sec: float = 120
    grant_cooldown_sec: float = 30
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _cooldown: dict[str, float] = field(default_factory=dict)
    _ready: bool = False
    audit: list[dict] = field(default_factory=list)

    async def startup_lock(self) -> None:
        try:
            await self.adapter.close()
        except Exception:
            _LOGGER.exception("启动校正上锁失败")
        self._ready = True

    def ready(self) -> bool:
        return self._ready

    async def open(
        self,
        *,
        reason: Literal["face_match", "booking_grant", "manual"],
        person_id: int | None = None,
        person_name: str = "",
        user_id: str | None = None,
        grant_id: str | None = None,
        command_id: str | None = None,
        extra_reasons: list[str] | None = None,
    ) -> tuple[DoorResult, str]:
        if not self._ready:
            return "denied", ""

        cooldown_key = grant_id or f"face:{person_id or person_name}" or "manual"
        cooldown_sec = self.grant_cooldown_sec if reason == "booking_grant" else (
            self.face_cooldown_sec if reason == "face_match" else 5
        )
        now = time.time()
        if now - self._cooldown.get(cooldown_key, 0) < cooldown_sec:
            return "denied", ""

        cid = command_id or str(uuid.uuid4())
        async with self._lock:
            # 二次检查冷却（单飞内）
            if time.time() - self._cooldown.get(cooldown_key, 0) < cooldown_sec:
                return "denied", ""
            ok = await self.adapter.open(self.open_seconds, cid)
            self._cooldown[cooldown_key] = time.time()
            result: DoorResult = "opened" if ok else "unknown"
            # 超时/失败：不连发第二次脉冲
            entry = {
                "ts": time.time(),
                "command_id": cid,
                "result": result,
                "reason": reason,
                "extra_reasons": extra_reasons or [],
                "person_id": person_id,
                "person_name": person_name,
                "user_id": user_id,
                "grant_id": grant_id,
            }
            self.audit.append(entry)
            cmd = DoorCommand(
                command_id=cid,
                door_id=self.door_id,
                seconds=self.open_seconds,
                reason=reason,
                grant_id=grant_id,
                user_id=user_id,
                person_id=person_id,
                person_name=person_name,
                ts=entry["ts"],
            )
            _LOGGER.info("门禁脉冲 result=%s cmd=%s", result, cmd.model_dump(by_alias=True))
            return result, cid

    async def close(self) -> bool:
        async with self._lock:
            return await self.adapter.close()

    def status(self) -> dict:
        return {"door_id": self.door_id, "ready": self._ready, "adapter": type(self.adapter).__name__}
