"""Fetches the chosen properties' Layla devices, with their readings and alarms, on a schedule."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LaylaApi, LaylaApiError
from .auth import LaylaAuthError, LaylaConnectError
from .const import DOMAIN
from .model import Device, parse_devices, temperature_unit
from .settings import Options

_LOGGER = logging.getLogger(__name__)


@dataclass
class LaylaData:
    devices: dict[str, Device] = field(default_factory=dict)
    temperature_unit: str = "F"
    # every property on the account (id -> name), chosen or not: the options form lists them
    properties: dict[str, str] = field(default_factory=dict)
    # what each device's answer held (its keys, and how many readings), for diagnostics
    shape: list[dict] = field(default_factory=list)
    # the chosen properties that didn't answer this time (id -> error): their devices are unavailable
    failed: dict[str, str] = field(default_factory=dict)


def _shape(body) -> list[dict]:
    if not isinstance(body, list):
        return [{"not_a_list": type(body).__name__}]
    return [
        {"keys": sorted(k for k in d if not k.startswith("_")), "latest_values": len(d.get("latest_values") or []), "connection_status": d.get("connection_status")}
        for d in body
        if isinstance(d, dict)
    ]


type LaylaConfigEntry = ConfigEntry[LaylaCoordinator]


class LaylaCoordinator(DataUpdateCoordinator[LaylaData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: LaylaApi, options: Options) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(minutes=options.update_minutes)
        )
        self.api = api
        self.options = options
        self._failing: set[str] = set()

    async def _async_update_data(self) -> LaylaData:
        try:
            # every time: the readings come in the unit the account is set to now
            unit = temperature_unit(await self.api.user())
            properties = await self.api.properties()
            body, failed = await self.api.devices(p for p in properties if self.options.wants_property(str(p["id"])))
            devices = parse_devices(body, recent=timedelta(minutes=self.options.online_minutes))
        except LaylaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (LaylaApiError, LaylaConnectError) as err:
            raise UpdateFailed(str(err)) from err
        names = {str(p["id"]): str(p.get("name") or p["id"]) for p in properties}
        # say so once when a property stops answering, and once when it's back
        for pid in failed.keys() - self._failing:
            _LOGGER.warning("Layla didn't answer for one of the properties (%s): its devices are unavailable", failed[pid])
        if self._failing - failed.keys():
            _LOGGER.info("Layla answers for every chosen property again")
        self._failing = set(failed)
        return LaylaData(devices=devices, temperature_unit=unit, properties=names, shape=_shape(body), failed=failed)
