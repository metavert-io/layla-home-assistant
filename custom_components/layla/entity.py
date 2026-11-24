"""The base for Layla's entities: one Home Assistant device per Layla sensor."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import LaylaCoordinator
from .model import Device


class LaylaEntity(CoordinatorEntity[LaylaCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = "Data from Layla"

    def __init__(self, coordinator: LaylaCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key
        self._attr_unique_id = f"{device_id}_{key}"
        d = self.device
        info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=d.title(coordinator.options.property_in_name) if d else "Layla",
            manufacturer=MANUFACTURER,
            model=d.model if d else None,
        )
        if d and d.serial:
            info["serial_number"] = d.serial
        if d and d.mac:
            info["connections"] = {(CONNECTION_NETWORK_MAC, d.mac.lower())}
        self._attr_device_info = info

    @property
    def device(self) -> Device | None:
        return self.coordinator.data.devices.get(self._device_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        d = self.device
        return super().available and d is not None and d.online


def add_as_they_appear(
    coordinator: LaylaCoordinator,
    add: Callable[[Iterable[Entity]], None],
    make: Callable[[Device], Iterable[tuple[str, Entity]]],
) -> Callable[[], None]:
    """Adds each device's entities now, and any new ones (a new sensor, a new reading) later."""
    seen: set[str] = set()

    @callback
    def check() -> None:
        new = []
        for d in (coordinator.data.devices if coordinator.data else {}).values():
            for key, ent in make(d):
                if key not in seen:
                    seen.add(key)
                    new.append(ent)
        if new:
            add(new)

    check()
    return coordinator.async_add_listener(check)
