"""Layla's readings, one sensor each, and the alarms active now."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LaylaConfigEntry, LaylaCoordinator
from .entity import LaylaEntity, add_as_they_appear
from .model import ALARMS, READINGS, Device


async def async_setup_entry(hass: HomeAssistant, entry: LaylaConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data

    def make(d: Device):
        yield f"{d.id}:alarms", LaylaAlarms(coordinator, d.id)
        for key in d.readings:
            if key in coordinator.options.readings:
                yield f"{d.id}:{key}", LaylaReading(coordinator, d.id, key)

    entry.async_on_unload(add_as_they_appear(coordinator, async_add_entities, make))


class LaylaReading(LaylaEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LaylaCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator, device_id, key)
        spec = READINGS[key]
        self._attr_name = spec["name"]
        if spec.get("device_class"):
            self._attr_device_class = SensorDeviceClass(spec["device_class"])
        if spec.get("icon"):
            self._attr_icon = spec["icon"]
        if spec.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if spec["unit"] != "temperature":
            self._attr_native_unit_of_measurement = spec["unit"]

    @property
    def native_unit_of_measurement(self) -> str | None:
        if READINGS[self._key]["unit"] == "temperature":
            return UnitOfTemperature.CELSIUS if self.coordinator.data.temperature_unit == "C" else UnitOfTemperature.FAHRENHEIT
        return self._attr_native_unit_of_measurement

    @property
    def native_value(self) -> float | None:
        d = self.device
        return d.readings.get(self._key) if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.device
        out: dict[str, Any] = {"layla_reading": self._key, "layla_device": self._device_id}
        if d:
            low, high = d.reading_range.get(self._key, (None, None))
            if low is not None:
                out["low"] = low
            if high is not None:
                out["high"] = high
            if d.reading_at.get(self._key):
                out["measured_at"] = d.reading_at[self._key]
        return out


class LaylaAlarms(LaylaEntity, SensorEntity):
    """How many of the device's alarms are active (snoozed ones too), and which (attributes)."""

    _attr_name = "Active alarms"
    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, coordinator: LaylaCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "active_alarms")

    @property
    def native_value(self) -> int | None:
        d = self.device
        return len(d.firing) if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.device
        firing = sorted(d.firing) if d else []
        return {
            "layla_alarms": firing,
            "labels": [ALARMS.get(a, {}).get("name", a.replace("_", " ")) for a in firing],
            "since": {a: d.firing[a] for a in firing if d.firing[a]} if d else {},
            "snoozed": sorted(d.snoozed) if d else [],
            "layla_device": self._device_id,
        }
