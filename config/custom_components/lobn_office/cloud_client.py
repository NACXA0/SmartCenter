"""总控 → 云端：预取授权与回执（HMAC）。"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .hmac_auth import make_headers
from .models import Grant, GrantAck

_LOGGER = logging.getLogger(__name__)


class CloudClient:
    def __init__(self, base_url: str, hmac_secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = hmac_secret

    def _path(self, url_path: str) -> str:
        return url_path

    async def pull_pending_grants(self, within_minutes: int = 15) -> list[Grant]:
        if not self.base_url or not self.secret:
            return []
        path = f"/internal/grants/pending?within_minutes={within_minutes}"
        body = b""
        headers = make_headers(self.secret, "GET", path.split("?")[0], body)
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
        headers = make_headers(self.secret, "POST", path, body)
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
        headers = make_headers(self.secret, "GET", path, b"")
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
        headers = make_headers(self.secret, "POST", path, body)
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
        headers = make_headers(self.secret, "GET", path, b"")
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

    async def consume_door_request(self, request_id: str | int, result: str = "opened") -> bool:
        path = f"/internal/door/requests/{request_id}/consume"
        body = json.dumps({"result": result}, ensure_ascii=False).encode()
        headers = make_headers(self.secret, "POST", path, body)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}{path}", headers=headers, content=body)
            return resp.status_code < 300
        except Exception:
            _LOGGER.exception("消费开门请求失败 id=%s", request_id)
            return False

    async def pull_settings(self) -> dict[str, Any]:
        if not self.base_url or not self.secret:
            return {}
        path = "/internal/settings"
        headers = make_headers(self.secret, "GET", path, b"")
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
