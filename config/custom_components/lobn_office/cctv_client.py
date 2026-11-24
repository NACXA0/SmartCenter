"""总控 → 监控：人脸入库（HMAC），云不落向量。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .hmac_auth import make_headers

_LOGGER = logging.getLogger(__name__)


class CctvClient:
    def __init__(self, enroll_url: str, hmac_secret: str) -> None:
        self.enroll_url = enroll_url
        self.secret = hmac_secret

    async def enroll_person(
        self,
        *,
        image: bytes,
        user_id: str,
        name: str,
        content_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        if not self.enroll_url or not self.secret:
            return {"ok": False, "error": "未配置监控入库地址"}
        parsed = urlparse(self.enroll_url)
        path = parsed.path or "/api/internal/persons/enroll"
        # multipart：签名对空 JSON 元数据 + 另传文件；简化为 JSON 元数据头 + raw 不方便
        # 契约：对固定 path 签名 body=元数据 JSON，文件用 multipart 字段 file
        meta = f'{{"user_id":"{user_id}","name":"{name}"}}'.encode()
        headers = make_headers(self.secret, "POST", path, meta)
        headers.pop("Content-Type", None)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self.enroll_url,
                    headers=headers,
                    data={"user_id": user_id, "name": name, "meta_sha_body": meta.decode()},
                    files={"file": ("face.jpg", image, content_type)},
                )
            if resp.status_code >= 300:
                return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text[:200]}
            return resp.json() if resp.content else {"ok": True}
        except Exception as exc:
            _LOGGER.exception("监控入库失败")
            return {"ok": False, "error": str(exc)}
