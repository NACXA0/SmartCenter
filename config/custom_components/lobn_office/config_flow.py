"""配置流：UI 增量添加，不改 HA 主干。每店独立 unique_id。"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

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
    CONF_GATE_NODE,
    CONF_GATE_STATE_ENTITY,
    CONF_GRANT_COOLDOWN,
    CONF_GRANT_PREFETCH_MIN,
    CONF_INNER_NODE,
    CONF_INNER_STATE_ENTITY,
    CONF_NIGHT_FACE_MODE,
    CONF_OPEN_SECONDS,
    CONF_OPEN_URL,
    CONF_ROOM_ID,
    CONF_STORE_ID,
    CONF_WECOM_WEBHOOK,
    DOMAIN,
)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_STORE_ID, default=1): vol.Coerce(int),
        vol.Optional(CONF_ROOM_ID, default=1): vol.Coerce(int),
        vol.Required(CONF_DOOR_ADAPTER, default="mqtt"): vol.In(
            ["mqtt", "mock", "http", "esp"]
        ),
        vol.Optional(CONF_GATE_NODE, default="front_gate"): str,
        vol.Optional(CONF_INNER_NODE, default="classroom_1"): str,
        vol.Optional(CONF_GATE_STATE_ENTITY, default=""): str,
        vol.Optional(CONF_INNER_STATE_ENTITY, default=""): str,
        vol.Optional(CONF_OPEN_URL, default=""): str,
        vol.Optional(CONF_CLOSE_URL, default=""): str,
        vol.Optional(CONF_ESP_BASE_URL, default=""): str,
        vol.Optional(CONF_ESP_TOKEN, default=""): str,
        vol.Optional(CONF_OPEN_SECONDS, default=5): vol.Coerce(float),
        vol.Optional(CONF_DOOR_METHOD, default="GET"): vol.In(["GET", "POST"]),
        vol.Optional(CONF_DOOR_TIMEOUT, default=3): vol.Coerce(float),
        vol.Optional(CONF_CLOUD_BASE_URL, default=""): str,
        vol.Optional(CONF_CLOUD_HMAC, default=""): str,
        vol.Optional(CONF_CCTV_EVENT_HMAC, default=""): str,
        vol.Optional(CONF_CCTV_ENROLL_URL, default=""): str,
        vol.Optional(CONF_CCTV_ENROLL_HMAC, default=""): str,
        vol.Optional(CONF_WECOM_WEBHOOK, default=""): str,
        vol.Optional(CONF_NIGHT_FACE_MODE, default="stricter"): vol.In(
            ["stricter", "alert_only"]
        ),
        vol.Optional(CONF_GRANT_PREFETCH_MIN, default=15): vol.Coerce(int),
        vol.Optional(CONF_FACE_COOLDOWN, default=120): vol.Coerce(float),
        vol.Optional(CONF_GRANT_COOLDOWN, default=30): vol.Coerce(float),
    }
)


class LobnOfficeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            store_id = int(user_input.get(CONF_STORE_ID) or 1)
            if store_id < 1:
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_USER,
                    errors={"base": "invalid_store_id"},
                )
            await self.async_set_unique_id(f"{DOMAIN}_{store_id}")
            self._abort_if_unique_id_configured()
            title = f"智慧办公室 · 店 {store_id}"
            return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(step_id="user", data_schema=STEP_USER)
