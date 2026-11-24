"""配置流：UI 增量添加，不改 HA 主干。"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
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
    CONF_FACE_COOLDOWN,
    CONF_GRANT_COOLDOWN,
    CONF_GRANT_PREFETCH_MIN,
    CONF_NIGHT_FACE_MODE,
    CONF_OPEN_SECONDS,
    CONF_OPEN_URL,
    CONF_WECOM_WEBHOOK,
    DOMAIN,
)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_DOOR_ADAPTER, default="mock"): vol.In(["mock", "http"]),
        vol.Optional(CONF_OPEN_URL, default=""): str,
        vol.Optional(CONF_CLOSE_URL, default=""): str,
        vol.Optional(CONF_OPEN_SECONDS, default=5): vol.Coerce(float),
        vol.Optional(CONF_DOOR_METHOD, default="GET"): vol.In(["GET", "POST"]),
        vol.Optional(CONF_DOOR_TIMEOUT, default=3): vol.Coerce(float),
        vol.Optional(CONF_CLOUD_BASE_URL, default=""): str,
        vol.Optional(CONF_CLOUD_HMAC, default=""): str,
        vol.Optional(CONF_CCTV_EVENT_HMAC, default=""): str,
        vol.Optional(CONF_CCTV_ENROLL_URL, default=""): str,
        vol.Optional(CONF_CCTV_ENROLL_HMAC, default=""): str,
        vol.Optional(CONF_WECOM_WEBHOOK, default=""): str,
        vol.Optional(CONF_NIGHT_FACE_MODE, default="stricter"): vol.In(["stricter", "alert_only"]),
        vol.Optional(CONF_GRANT_PREFETCH_MIN, default=15): vol.Coerce(int),
        vol.Optional(CONF_FACE_COOLDOWN, default=120): vol.Coerce(float),
        vol.Optional(CONF_GRANT_COOLDOWN, default=30): vol.Coerce(float),
    }
)


class LobnOfficeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="智慧办公室", data=user_input)
        return self.async_show_form(step_id="user", data_schema=STEP_USER)
