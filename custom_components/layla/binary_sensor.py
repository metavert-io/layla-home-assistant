"""Layla's alarms (on while active, snoozed or not) and whether each sensor is online."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LaylaConfigEntry, LaylaCoordinator
from .entity import LaylaEntity, add_as_they_appear
from .model import ALARMS, Device
from .registry import existing_alarms


async def async_setup_entry(hass: HomeAssistant, entry: LaylaConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    options = coordinator.options
    # with the device's own alarms wanted, an alarm sensor stays once it exists (e.g. after its alarm fired)
    existing = existing_alarms(hass, entry) if options.device_alarms else {}

    def make(d: Device):
        yield f"{d.id}:online", LaylaOnline(coordinator, d.id)
        keys = set(d.alarms_offered(options.alarms, options.device_alarms)) | existing.get(d.id, set())
        for key in ALARMS:
            if key in keys:
                yield f"{d.id}:{key}", LaylaAlarm(coordinator, d.id, key)

    entry.async_on_unload(add_as_they_appear(coordinator, async_add_entities, make))


class LaylaAlarm(LaylaEntity, BinarySensorEntity):
    def __init__(self, coordinator: LaylaCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator, device_id, key)
        self._attr_name = ALARMS[key]["name"]
        self._attr_device_class = BinarySensorDeviceClass(ALARMS[key]["device_class"])

    @property
    def is_on(self) -> bool | None:
        d = self.device
        return self._key in d.firing if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.device
        out: dict[str, Any] = {"layla_alarm": self._key, "layla_device": self._device_id}
        if d and d.firing.get(self._key):
            out["since"] = d.firing[self._key]
        if d and self._key in d.snoozed:
            out["snoozed"] = True
        return out


class LaylaOnline(LaylaEntity, BinarySensorEntity):
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LaylaCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "online")

    @property
    def available(self) -> bool:  # online or not, it says so
        return self.coordinator.last_update_success and self.device is not None

    @property
    def is_on(self) -> bool | None:
        d = self.device
        return d.online if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.device
        out: dict[str, Any] = {"layla_online": True, "layla_device": self._device_id}
        if d:
            out["mac"] = d.mac
            out["last_report"] = d.updated_at
            if d.pillar:
                out["mode"] = d.pillar
        return out
