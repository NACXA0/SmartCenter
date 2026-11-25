"""捕捉唤醒指示。"""

from __future__ import annotations

import time

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN]["runtime"]
    async_add_entities([LobnCaptureWakeBinary(runtime)])


class LobnCaptureWakeBinary(BinarySensorEntity):
    _attr_name = "门口捕捉唤醒"
    _attr_unique_id = "lobn_office_capture_wake"
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, runtime: dict) -> None:
        self._runtime = runtime

    @property
    def is_on(self) -> bool:
        sense = self._runtime["sense"]
        now = time.time()
        recent_pir = now - getattr(sense, "_last_pir_assist", 0) < sense.assist_seconds
        recent_btn = now - getattr(sense, "_last_btn_assist", 0) < sense.assist_seconds
        return bool(recent_pir or recent_btn)
