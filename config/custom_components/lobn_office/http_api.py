"""HTTP 入口：监控事件（HMAC）、店员手工开门（HA 鉴权）。"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .hmac_auth import NonceCache, verify
from .models import CctvEvent

_LOGGER = logging.getLogger(__name__)
_NONCES = NonceCache()


class LobnEventsView(HomeAssistantView):
    """POST /api/lobn_office/events — 监控上报，事件本身不开门。"""

    url = "/api/lobn_office/events"
    name = "api:lobn_office:events"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        runtime = self.hass.data.get(DOMAIN, {}).get("runtime")
        if runtime is None:
            return web.json_response({"ok": False, "error": "集成未就绪"}, status=503)
        body = await request.read()
        secret = runtime["cctv_event_hmac"]
        ok, err = verify(
            secret,
            request.headers.get("X-Lobn-Timestamp", ""),
            request.headers.get("X-Lobn-Nonce", ""),
            request.headers.get("X-Lobn-Signature", ""),
            "POST",
            "/api/lobn_office/events",
            body,
            nonce_cache=_NONCES,
        )
        if not ok:
            return web.json_response({"ok": False, "error": err}, status=401)
        try:
            event = CctvEvent.model_validate_json(body)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"载荷无效: {exc}"}, status=400)

        # 映射 HA 事件（事实），策略异步决策
        self.hass.bus.async_fire(f"lobn_office_{event.type}", event.model_dump(by_alias=True))
        result = await runtime["policy"].on_cctv_event(event)
        return web.json_response({"ok": True, "result": result})


class LobnManualOpenView(HomeAssistantView):
    """POST /api/lobn_office/door/open — 需 HA 登录。"""

    url = "/api/lobn_office/door/open"
    name = "api:lobn_office:door_open"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        runtime = self.hass.data.get(DOMAIN, {}).get("runtime")
        if runtime is None:
            return web.json_response({"ok": False, "error": "集成未就绪"}, status=503)
        result = await runtime["policy"].manual_open(actor="ha_api")
        return web.json_response({"ok": True, "result": result})


class LobnLocalFaceEnrollView(HomeAssistantView):
    """POST /api/lobn_office/face/enroll — 店员本地面录入（图像不经云端）。需 HA 登录。

    multipart: file + user_id + name(可选)
    """

    url = "/api/lobn_office/face/enroll"
    name = "api:lobn_office:face_enroll_local"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        runtime = self.hass.data.get(DOMAIN, {}).get("runtime")
        if runtime is None:
            return web.json_response({"ok": False, "error": "集成未就绪"}, status=503)
        reader = await request.multipart()
        user_id = ""
        name = ""
        image: bytes | None = None
        content_type = "image/jpeg"
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "user_id":
                user_id = (await part.text()).strip()
            elif part.name == "name":
                name = (await part.text()).strip()
            elif part.name == "file":
                image = await part.read(decode=False)
                content_type = part.headers.get("Content-Type", content_type) or "image/jpeg"
        if not user_id or not image:
            return web.json_response({"ok": False, "error": "需要 user_id 与 file"}, status=400)
        if len(image) > 2 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "图片过大"}, status=400)
        cctv = runtime["cctv"]
        result = await cctv.enroll_person(
            image=image,
            user_id=user_id,
            name=name or user_id,
            content_type=content_type,
        )
        if result.get("ok"):
            from .models import PersonRecord

            pid = int(result.get("person_id", 0) or 0)
            if pid:
                runtime["hot"].upsert_person(
                    PersonRecord(person_id=pid, user_id=user_id, name=name or user_id)
                )
            runtime["audit"].append(
                "face_enroll_local",
                user_id=user_id,
                person_id=pid,
                actor="ha_api",
            )
            return web.json_response({"ok": True, "person_id": pid, "channel": "local"})
        return web.json_response(
            {"ok": False, "error": result.get("error", "入库失败")},
            status=502,
        )


@callback
def async_register_views(hass: HomeAssistant) -> None:
    hass.http.register_view(LobnEventsView(hass))
    hass.http.register_view(LobnManualOpenView(hass))
    hass.http.register_view(LobnLocalFaceEnrollView(hass))
