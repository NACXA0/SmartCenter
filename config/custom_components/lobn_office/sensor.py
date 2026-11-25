"""温湿度与器件健康、最近告警。"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN]["runtime"]
    async_add_entities(
        [
            LobnTempSensor(runtime),
            LobnHumiditySensor(runtime),
            LobnDeviceHealthSensor(runtime, "dht", "温湿度健康"),
            LobnDeviceHealthSensor(runtime, "pir", "人体红外健康"),
            LobnDeviceHealthSensor(runtime, "button", "按钮健康"),
            LobnLastAlertSensor(runtime),
        ]
    )


class _SenseBase(SensorEntity):
    def __init__(self, runtime: dict) -> None:
        self._runtime = runtime

    @property
    def sense(self):
        return self._runtime["sense"]


class LobnTempSensor(_SenseBase):
    _attr_name = "门口温度"
    _attr_unique_id = "lobn_office_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        if self.sense.dht_health == "unavailable":
            return None
        return self.sense.temperature_c

    @property
    def available(self) -> bool:
        return self.sense.dht_health != "unavailable" and self.sense.temperature_c is not None


class LobnHumiditySensor(_SenseBase):
    _attr_name = "门口湿度"
    _attr_unique_id = "lobn_office_humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        if self.sense.dht_health == "unavailable":
            return None
        return self.sense.humidity_pct

    @property
    def available(self) -> bool:
        return self.sense.dht_health != "unavailable" and self.sense.humidity_pct is not None


class LobnDeviceHealthSensor(_SenseBase):
    def __init__(self, runtime: dict, key: str, name: str) -> None:
        super().__init__(runtime)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"lobn_office_health_{key}"

    @property
    def native_value(self):
        return getattr(self.sense, f"{self._key}_health", "unavailable")


class LobnLastAlertSensor(_SenseBase):
    _attr_name = "最近传感器告警"
    _attr_unique_id = "lobn_office_last_alert"

    @property
    def native_value(self):
        alert = self.sense.last_alert
        return alert.summary if alert else "无"

    @property
    def extra_state_attributes(self):
        alert = self.sense.last_alert
        return alert.model_dump(by_alias=True) if alert else {}
