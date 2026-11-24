"""AI 管家意图：只读查询；开门必须带 CONFIRMED_OPEN。"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import ATTR_CONFIRM, CONFIRM_OPEN, DOMAIN


async def async_setup_intents(hass: HomeAssistant) -> None:
    intent.async_register(hass, QueryGrantsIntent())
    intent.async_register(hass, QueryAuditIntent())
    intent.async_register(hass, ConfirmedOpenIntent())


class QueryGrantsIntent(intent.IntentHandler):
    intent_type = "LobnQueryGrants"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        hot = hass.data[DOMAIN]["runtime"]["hot"]
        grants = hot.get_active_grants()
        speech = f"当前有效授权 {len(grants)} 条。"
        if grants:
            speech += " ".join(f"{g.grant_id} 用户{g.user_id}" for g in grants[:5])
        resp = intent_obj.create_response()
        resp.async_set_speech(speech)
        return resp


class QueryAuditIntent(intent.IntentHandler):
    intent_type = "LobnQueryAudit"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        rows = hass.data[DOMAIN]["runtime"]["audit"].recent(10)
        speech = f"最近审计 {len(rows)} 条。"
        for r in rows[-3:]:
            speech += f" {r.get('action')}:{r.get('result', r.get('reason', ''))}"
        resp = intent_obj.create_response()
        resp.async_set_speech(speech)
        return resp


class ConfirmedOpenIntent(intent.IntentHandler):
    intent_type = "LobnConfirmedOpen"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        token = intent_obj.slots.get(ATTR_CONFIRM, {}).get("value")
        resp = intent_obj.create_response()
        if token != CONFIRM_OPEN:
            resp.async_set_speech("需要店员确认令牌才能开门，已拒绝。")
            return resp
        result = await hass.data[DOMAIN]["runtime"]["policy"].manual_open(actor="butler")
        resp.async_set_speech(f"开门结果：{result.get('action')}")
        return resp
