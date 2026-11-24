"""lobn_office：自定义集成入口。不修改 HA 主干，升级只升 homeassistant 版本。

模块级避免强依赖 homeassistant，便于热路径/HMAC/门禁单测。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .const import (
    CONF_CCTV_ENROLL_HMAC,
    CONF_CCTV_ENROLL_URL,
    CONF_CCTV_EVENT_HMAC,
    CONF_CLOSE_URL,
    CONF_CLOUD_BASE_URL,
    CONF_CLOUD_HMAC,
    CONF_DOOR_ADAPTER,
    CONF_DOOR_METHOD,
    CONF_DOOR_TIMEOUT,
    CONF_FACE_COOLDOWN,
    CONF_GRANT_COOLDOWN,
    CONF_GRANT_PREFETCH_MIN,
    CONF_NIGHT_FACE_MODE,
    CONF_OPEN_SECONDS,
    CONF_OPEN_URL,
    CONF_WECOM_WEBHOOK,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform
    from homeassistant.core import ServiceCall

    from .audit import AuditLog
    from .cctv_client import CctvClient
    from .cloud_client import CloudClient
    from .coordinator import GrantCoordinator
    from .door import DoorController, HttpRelayAdapter, MockDoorAdapter
    from .hot_path import InMemoryHotPath
    from .http_api import async_register_views
    from .intent import async_setup_intents
    from .models import GrantAck, PersonRecord
    from .notify import WeComNotifier
    from .policy import AccessPolicy

    data = entry.data
    adapter_name = data.get(CONF_DOOR_ADAPTER, "mock")
    if adapter_name == "http" and data.get(CONF_OPEN_URL):
        adapter = HttpRelayAdapter(
            open_url=data[CONF_OPEN_URL],
            close_url=data.get(CONF_CLOSE_URL, ""),
            method=data.get(CONF_DOOR_METHOD, "GET"),
            timeout_sec=float(data.get(CONF_DOOR_TIMEOUT, 3)),
        )
    else:
        adapter = MockDoorAdapter()

    door = DoorController(
        adapter=adapter,
        open_seconds=float(data.get(CONF_OPEN_SECONDS, 5)),
        face_cooldown_sec=float(data.get(CONF_FACE_COOLDOWN, 120)),
        grant_cooldown_sec=float(data.get(CONF_GRANT_COOLDOWN, 30)),
    )
    hot = InMemoryHotPath()
    notify = WeComNotifier(webhook=data.get(CONF_WECOM_WEBHOOK, ""))
    audit_dir = Path(hass.config.config_dir) / ".lobn_audit"
    audit = AuditLog(audit_dir)
    cloud = CloudClient(data.get(CONF_CLOUD_BASE_URL, ""), data.get(CONF_CLOUD_HMAC, ""))
    cctv = CctvClient(data.get(CONF_CCTV_ENROLL_URL, ""), data.get(CONF_CCTV_ENROLL_HMAC, ""))

    async def on_ack(ack: GrantAck) -> None:
        audit.append(
            "grant_ack",
            grant_id=ack.grant_id,
            command_id=ack.command_id,
            result=ack.result,
            correlation_id=ack.correlation_id,
        )
        await cloud.ack_grant(ack)

    policy = AccessPolicy(
        door=door,
        hot=hot,
        notify=notify,
        audit=audit,
        night_face_mode=data.get(CONF_NIGHT_FACE_MODE, "stricter"),
        on_ack=on_ack,
    )

    coordinator = GrantCoordinator(
        hass,
        cloud,
        hot,
        prefetch_minutes=int(data.get(CONF_GRANT_PREFETCH_MIN, 15)),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["runtime"] = {
        "door": door,
        "hot": hot,
        "policy": policy,
        "notify": notify,
        "audit": audit,
        "cloud": cloud,
        "cctv": cctv,
        "coordinator": coordinator,
        "cctv_event_hmac": data.get(CONF_CCTV_EVENT_HMAC, ""),
    }

    await door.startup_lock()
    await notify.start()
    await coordinator.async_config_entry_first_refresh()
    async_register_views(hass)
    await async_setup_intents(hass)
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.LOCK])

    async def svc_manual_open(call: ServiceCall) -> None:
        await policy.manual_open(actor=str(call.data.get("actor", "service")))

    async def svc_refresh(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    async def svc_disable_person(call: ServiceCall) -> None:
        pid = int(call.data["person_id"])
        hot.disable_person(pid)
        audit.append("disable_person", person_id=pid)

    async def svc_upsert_person(call: ServiceCall) -> None:
        hot.upsert_person(
            PersonRecord(
                person_id=int(call.data["person_id"]),
                user_id=str(call.data.get("user_id", "")),
                name=str(call.data.get("name", "")),
                enabled=bool(call.data.get("enabled", True)),
            )
        )

    hass.services.async_register(DOMAIN, "manual_open", svc_manual_open)
    hass.services.async_register(DOMAIN, "refresh_grants", svc_refresh)
    hass.services.async_register(DOMAIN, "disable_person", svc_disable_person)
    hass.services.async_register(DOMAIN, "upsert_person", svc_upsert_person)

    entry.async_create_background_task(hass, _face_bridge_loop(hass), "lobn_face_bridge")
    entry.async_create_background_task(hass, _door_request_loop(hass), "lobn_door_requests")
    _LOGGER.info("lobn_office 已加载（custom_components，主干可独立升级）")
    return True


async def _door_request_loop(hass: HomeAssistant) -> None:
    """拉取小程序按钮开门请求 → open_by_grant。"""
    from .cloud_client import CloudClient
    from .hot_path import InMemoryHotPath
    from .policy import AccessPolicy

    while True:
        try:
            runtime = hass.data.get(DOMAIN, {}).get("runtime")
            if runtime:
                cloud: CloudClient = runtime["cloud"]
                hot: InMemoryHotPath = runtime["hot"]
                policy: AccessPolicy = runtime["policy"]
                items = await cloud.pull_door_requests()
                for item in items:
                    grant_id = str(item.get("grant_id", ""))
                    request_id = item.get("request_id")
                    if not grant_id or request_id is None:
                        continue
                    # 确保热名单有该授权（可能刚支付尚未到预取周期）
                    if hot.grants.get(grant_id) is None:
                        grants = await cloud.pull_pending_grants(15)
                        for g in grants:
                            hot.upsert_grant(g)
                    result = await policy.open_by_grant(grant_id)
                    await cloud.consume_door_request(request_id, result=str(result.get("action", "opened")))
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("开门请求循环异常")
        await asyncio.sleep(3)


async def _face_bridge_loop(hass: HomeAssistant) -> None:
    from .cctv_client import CctvClient
    from .cloud_client import CloudClient
    from .hot_path import InMemoryHotPath
    from .models import PersonRecord

    while True:
        try:
            runtime = hass.data.get(DOMAIN, {}).get("runtime")
            if runtime:
                cloud: CloudClient = runtime["cloud"]
                cctv: CctvClient = runtime["cctv"]
                hot: InMemoryHotPath = runtime["hot"]
                items = await cloud.pull_face_pending()
                for item in items:
                    staging_id = str(item.get("id", ""))
                    user_id = str(item.get("user_id", ""))
                    name = str(item.get("name") or user_id)
                    image_b64 = item.get("image_base64")
                    image_url = item.get("download_url")
                    image: bytes | None = None
                    if image_b64:
                        import base64

                        image = base64.b64decode(image_b64)
                    elif image_url:
                        import httpx

                        async with httpx.AsyncClient(timeout=30) as client:
                            r = await client.get(image_url)
                            if r.status_code < 300:
                                image = r.content
                    if not image:
                        continue
                    result = await cctv.enroll_person(image=image, user_id=user_id, name=name)
                    if result.get("ok"):
                        pid = int(result.get("person_id", 0) or 0)
                        if pid:
                            hot.upsert_person(PersonRecord(person_id=pid, user_id=user_id, name=name))
                        await cloud.complete_face(staging_id, "accepted")
                    else:
                        await cloud.complete_face(staging_id, "rejected")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("人脸桥接循环异常")
        await asyncio.sleep(20)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["lock"])
    runtime = hass.data.get(DOMAIN, {}).pop("runtime", None)
    if runtime:
        await runtime["notify"].stop()
    return unload_ok
