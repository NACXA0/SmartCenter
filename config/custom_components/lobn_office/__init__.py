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
    CONF_ESP_BASE_URL,
    CONF_ESP_TOKEN,
    CONF_FACE_COOLDOWN,
    CONF_GRANT_COOLDOWN,
    CONF_GRANT_PREFETCH_MIN,
    CONF_NIGHT_FACE_MODE,
    CONF_OPEN_SECONDS,
    CONF_OPEN_URL,
    CONF_ROOM_ID,
    CONF_STORE_ID,
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

    from .alerts import AlertHub
    from .audit import AuditLog
    from .cctv_client import CctvClient
    from .cloud_client import CloudClient
    from .coordinator import GrantCoordinator
    from .door import DoorController, EspDoorAdapter, HttpRelayAdapter, MockDoorAdapter
    from .hot_path import InMemoryHotPath
    from .http_api import async_register_views
    from .intent import async_setup_intents
    from .models import GrantAck, PersonRecord
    from .notify import WeComNotifier
    from .policy import AccessPolicy
    from .sense import SenseRuntime

    data = entry.data
    adapter_name = data.get(CONF_DOOR_ADAPTER, "mock")
    timeout_sec = float(data.get(CONF_DOOR_TIMEOUT, 3))
    if adapter_name == "esp" and data.get(CONF_ESP_BASE_URL):
        adapter = EspDoorAdapter(
            base_url=data[CONF_ESP_BASE_URL],
            token=data.get(CONF_ESP_TOKEN, ""),
            timeout_sec=timeout_sec,
        )
    elif adapter_name == "http" and data.get(CONF_OPEN_URL):
        adapter = HttpRelayAdapter(
            open_url=data[CONF_OPEN_URL],
            close_url=data.get(CONF_CLOSE_URL, ""),
            method=data.get(CONF_DOOR_METHOD, "GET"),
            timeout_sec=timeout_sec,
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
    audit_dir = Path(hass.config.config_dir) / "data" / "lobn_office"
    audit = AuditLog(audit_dir)
    store_id = int(data.get(CONF_STORE_ID) or 1)
    room_id = int(data.get(CONF_ROOM_ID) or store_id)
    cloud = CloudClient(
        data.get(CONF_CLOUD_BASE_URL, ""),
        data.get(CONF_CLOUD_HMAC, ""),
        store_id=store_id,
    )
    cctv = CctvClient(data.get(CONF_CCTV_ENROLL_URL, ""), data.get(CONF_CCTV_ENROLL_HMAC, ""))

    sense = SenseRuntime()
    alert_hub = AlertHub(audit=audit, notify=notify, cloud=cloud, sense=sense)
    sense.emit_alert = alert_hub.publish

    async def _capture(source: str, seconds: float):
        return await cctv.capture_assist(source, seconds)

    sense.capture_assist = _capture

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
        cloud=cloud,
        room_id=room_id,
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
        "audit_dir": audit_dir,
        "cloud": cloud,
        "cctv": cctv,
        "sense": sense,
        "alerts": alert_hub,
        "coordinator": coordinator,
        "cctv_event_hmac": data.get(CONF_CCTV_EVENT_HMAC, ""),
        "esp_token": data.get(CONF_ESP_TOKEN, ""),
        "door_adapter_name": adapter_name,
        "version": _component_version(),
    }

    await door.startup_lock()
    await notify.start()
    await alert_hub.start()
    await coordinator.async_config_entry_first_refresh()
    async_register_views(hass)
    await async_setup_intents(hass)
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]
    )

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
    entry.async_create_background_task(hass, _heartbeat_loop(hass), "lobn_heartbeat")
    entry.async_create_background_task(hass, _sense_watch_loop(hass), "lobn_sense_watch")
    _LOGGER.info("lobn_office 已加载（custom_components，主干可独立升级）")
    return True


def _component_version() -> str:
    try:
        import json

        manifest = Path(__file__).with_name("manifest.json")
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version", ""))
    except Exception:
        return ""


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
                    action = str(result.get("action", "opened"))
                    command_id = str(result.get("command_id") or "")
                    passage_people = 0
                    passage_strangers = 0
                    if action == "opened" and command_id:
                        cctv = runtime.get("cctv")
                        door = runtime.get("door")
                        secs = float(getattr(door, "open_seconds", 5) if door else 5)
                        if cctv is not None:
                            await cctv.start_passage(command_id, seconds=secs)
                            await asyncio.sleep(min(secs, 120))
                            summary = await cctv.stop_passage(command_id)
                            passage_people = int(summary.get("people_count") or summary.get("people") or 0)
                            passage_strangers = int(
                                summary.get("stranger_count") or summary.get("strangers") or 0
                            )
                    await cloud.consume_door_request(
                        request_id,
                        result=action,
                        command_id=command_id or None,
                        passage_people=passage_people,
                        passage_strangers=passage_strangers,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("开门请求循环异常")
        await asyncio.sleep(3)


async def _heartbeat_loop(hass: HomeAssistant) -> None:
    """每 60s 上报总控心跳，并刷入门禁内存审计。"""
    from .audit import flush_door_audit
    from .cloud_client import CloudClient
    from .door import DoorController
    from .hot_path import InMemoryHotPath

    while True:
        try:
            runtime = hass.data.get(DOMAIN, {}).get("runtime")
            if runtime:
                cloud: CloudClient = runtime["cloud"]
                hot: InMemoryHotPath = runtime["hot"]
                door: DoorController = runtime["door"]
                await cloud.send_heartbeat(
                    door_adapter=str(runtime.get("door_adapter_name") or type(door.adapter).__name__),
                    hot_persons=len(hot.persons_by_id),
                    version=str(runtime.get("version") or ""),
                )
                audit_dir = runtime.get("audit_dir")
                if audit_dir is not None and door.audit:
                    await hass.async_add_executor_job(flush_door_audit, audit_dir, door.audit)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("心跳循环异常")
        await asyncio.sleep(60)



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


async def _sense_watch_loop(hass: HomeAssistant) -> None:
    """长按/过期检查 + ESP health 异常脉冲告警；同步站点辅助策略。"""
    from .door import EspDoorAdapter
    from .sense import SenseRuntime

    while True:
        try:
            runtime = hass.data.get(DOMAIN, {}).get("runtime")
            if runtime:
                sense: SenseRuntime = runtime["sense"]
                await sense.tick()
                settings = await runtime["cloud"].pull_settings()
                if settings:
                    if "pir_assist_enabled" in settings:
                        sense.pir_assist_enabled = bool(settings["pir_assist_enabled"])
                    if "button_assist_enabled" in settings:
                        sense.button_assist_enabled = bool(settings["button_assist_enabled"])
                    for key in ("reenable_pir", "reenable_button", "reenable_dht"):
                        if settings.get(key):
                            sense.reenable_sensor(key.replace("reenable_", ""))
                adapter = runtime["door"].adapter
                if isinstance(adapter, EspDoorAdapter):
                    health = await adapter.health()
                    if health and str(health.get("door")) == "pulsing":
                        cid = str(health.get("command_id") or "")
                        if cid and cid != adapter.last_command_id:
                            await sense.alert_unexpected_pulse(cid)
                        elif not cid:
                            await sense.alert_unexpected_pulse(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("感知巡检异常")
        await asyncio.sleep(5)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["lock", "sensor", "binary_sensor"]
    )
    runtime = hass.data.get(DOMAIN, {}).pop("runtime", None)
    if runtime:
        await runtime["notify"].stop()
        alerts = runtime.get("alerts")
        if alerts is not None:
            await alerts.stop()
    return unload_ok
