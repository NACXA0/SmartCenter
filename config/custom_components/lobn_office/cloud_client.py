"""总控 → 云端：预取授权与回执（HMAC，按店隔离）。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .hmac_auth import make_headers
from .models import AlertRecord, Grant, GrantAck

_LOGGER = logging.getLogger(__name__)


class CloudClient:
    def __init__(self, base_url: str, hmac_secret: str, store_id: int = 1) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = hmac_secret
        self.store_id = int(store_id or 1)

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        return make_headers(self.secret, method, path, body, store_id=self.store_id)

    async def pull_pending_grants(self, within_minutes: int = 15) -> list[Grant]:
        if not self.base_url or not self.secret:
            return []
        path = f"/internal/grants/pending?within_minutes={within_minutes}"
        body = b""
        headers = self._headers("GET", path.split("?")[0], body)
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code >= 300:
                _LOGGER.warning("拉取授权失败 HTTP %s", resp.status_code)
                return []
            data = resp.json()
            items = data.get("items", data if isinstance(data, list) else [])
            return [Grant.model_validate(x) for x in items]
        except Exception:
            _LOGGER.exception("拉取授权异常")
            return []

    async def ack_grant(self, ack: GrantAck) -> bool:
        if not self.base_url or not self.secret:
            return False
        path = f"/internal/grants/{ack.grant_id}/ack"
        body = json.dumps(ack.model_dump(by_alias=True), ensure_ascii=False).encode()
        headers = self._headers("POST", path, body)
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("回执失败 grant=%s", ack.grant_id)
            return False

    async def pull_face_pending(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.secret:
            return []
        path = "/internal/face/pending"
        headers = self._headers("GET", path, b"")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
            if resp.status_code >= 300:
                return []
            data = resp.json()
            return data.get("items", [])
        except Exception:
            _LOGGER.exception("拉取人脸暂存失败")
            return []

    async def complete_face(self, staging_id: str, status: str) -> bool:
        path = f"/internal/face/{staging_id}/complete"
        body = json.dumps({"status": status}, ensure_ascii=False).encode()
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("人脸完成回调失败")
            return False

    async def pull_door_requests(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.secret:
            return []
        path = "/internal/door/requests/pending"
        headers = self._headers("GET", path, b"")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
            if resp.status_code >= 300:
                return []
            data = resp.json()
            return data.get("items", [])
        except Exception:
            _LOGGER.exception("拉取开门请求失败")
            return []

    async def consume_door_request(
        self,
        request_id: str | int,
        result: str = "opened",
        *,
        command_id: str | None = None,
        passage_people: int | None = None,
        passage_strangers: int | None = None,
    ) -> bool:
        path = f"/internal/door/requests/{request_id}/consume"
        payload: dict[str, Any] = {"result": result}
        if command_id is not None:
            payload["command_id"] = command_id
        if passage_people is not None:
            payload["passage_people"] = int(passage_people)
        if passage_strangers is not None:
            payload["passage_strangers"] = int(passage_strangers)
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("消费开门请求失败 id=%s", request_id)
            return False

    async def report_door_status(
        self,
        room_id: int = 1,
        *,
        inner_status: str | None = None,
        gate_status: str | None = None,
        gate_connected: bool | None = None,
    ) -> bool:
        if not self.base_url or not self.secret:
            return False
        path = "/internal/doors/status"
        payload: dict[str, Any] = {"room_id": int(room_id)}
        if inner_status is not None:
            payload["inner_status"] = inner_status
        if gate_status is not None:
            payload["gate_status"] = gate_status
        if gate_connected is not None:
            payload["gate_connected"] = bool(gate_connected)
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            if resp.status_code >= 300:
                _LOGGER.warning("上报门状态失败 HTTP %s", resp.status_code)
                return False
            return True
        except Exception:
            _LOGGER.exception("上报门状态异常 room=%s", room_id)
            return False

    async def send_heartbeat(
        self,
        door_adapter: str = "",
        hot_persons: int = 0,
        version: str = "",
    ) -> bool:
        if not self.base_url or not self.secret:
            return False
        path = "/internal/center/heartbeat"
        body = json.dumps(
            {
                "door_adapter": door_adapter,
                "hot_persons": int(hot_persons),
                "version": version,
            },
            ensure_ascii=False,
        ).encode()
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            if resp.status_code >= 300:
                _LOGGER.warning("心跳失败 HTTP %s", resp.status_code)
                return False
            return True
        except Exception:
            _LOGGER.exception("心跳异常")
            return False

    async def pull_settings(self) -> dict[str, Any]:
        if not self.base_url or not self.secret:
            return {}
        path = "/internal/settings"
        headers = self._headers("GET", path, b"")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
            if resp.status_code >= 300:
                return {}
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            _LOGGER.exception("拉取站点配置失败")
            return {}

    async def push_alert(self, alert: AlertRecord) -> bool:
        if not self.base_url or not self.secret:
            return False
        path = "/internal/alerts"
        body = json.dumps(alert.model_dump(by_alias=True), ensure_ascii=False).encode()
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("推送告警失败 id=%s", alert.alert_id)
            return False

    async def pull_alert_acks(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.secret:
            return []
        path = "/internal/alerts/pending-acks"
        headers = self._headers("GET", path, b"")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
            if resp.status_code >= 300:
                return []
            data = resp.json()
            return data.get("items", [])
        except Exception:
            _LOGGER.exception("拉取告警确认失败")
            return []

    async def ack_alert_pulled(self, alert_id: str) -> bool:
        if not self.base_url or not self.secret or not alert_id:
            return False
        path = f"/internal/alerts/{alert_id}/pulled"
        body = b"{}"
        headers = self._headers("POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("确认告警已拉回失败 id=%s", alert_id)
            return False

    async def pull_print_jobs(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.secret:
            return []
        path = "/internal/print/jobs/pending"
        headers = self._headers("GET", path, b"")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
            if resp.status_code >= 300:
                return []
            data = resp.json()
            return data.get("items", [])
        except Exception:
            _LOGGER.exception("拉取打印任务失败")
            return []
