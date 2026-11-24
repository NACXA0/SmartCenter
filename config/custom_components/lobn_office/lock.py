"""Lock 实体：面板上手动开锁仍走总控门禁。"""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    async_add_entities([LobnDoorLock(runtime)])


class LobnDoorLock(LockEntity):
    _attr_name = "办公室门禁"
    _attr_unique_id = "lobn_office_main_door"
    _attr_is_locked = True

    def __init__(self, runtime: dict) -> None:
        self._runtime = runtime

    async def async_unlock(self, **kwargs) -> None:
        result = await self._runtime["policy"].manual_open(actor="ha_lock")
        self._attr_is_locked = result.get("action") != "opened"
        self.async_write_ha_state()

    async def async_lock(self, **kwargs) -> None:
        await self._runtime["door"].close()
        self._attr_is_locked = True
        self.async_write_ha_state()
