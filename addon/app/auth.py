from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException, Request


@dataclass
class Actor:
    kind: str  # ha | relay | dev
    id: str
    is_admin: bool = False


async def require_staff(
    request: Request,
    x_hass_user_id: str | None = Header(default=None, alias="X-Hass-User-ID"),
    x_hass_is_admin: str | None = Header(default=None, alias="X-Hass-Is-Admin"),
    x_relay_token: str | None = Header(default=None, alias="X-Lobn-Relay-Token"),
) -> Actor:
    """Ingress 注入 HA 头；云端中继用共享 token；开发态可放行。"""
    settings = request.app.state.settings
    if x_relay_token and settings.cloud_hmac_secret and x_relay_token == settings.cloud_hmac_secret:
        return Actor(kind="relay", id="cloud-relay", is_admin=False)

    if x_hass_user_id:
        admin = (x_hass_is_admin or "").lower() in ("1", "true", "yes")
        if not admin and not settings.allow_dev_auth:
            # 非管理员默认拒绝辅助采集写操作；只读可另开
            raise HTTPException(403, "staff_admin_required")
        return Actor(kind="ha", id=x_hass_user_id, is_admin=admin or settings.allow_dev_auth)

    if settings.allow_dev_auth:
        return Actor(kind="dev", id="dev", is_admin=True)

    # Supervisor token 探活（可选）
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token and x_hass_user_id is None:
        raise HTTPException(401, "ha_auth_required")
    raise HTTPException(401, "unauthorized")


async def supervisor_healthy() -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return True
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                "http://supervisor/core/api/config",
                headers={"Authorization": f"Bearer {token}"},
            )
            return r.status_code < 500
    except Exception:
        return False
