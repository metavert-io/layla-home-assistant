"""The Layla integration: a Layla sensor's readings (noise, people, temperature, air) and alarms
(smoke, CO, noise, crowding, security), from Layla's cloud. Read-only."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LaylaApi
from .const import CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import LaylaConfigEntry, LaylaCoordinator
from .registry import remove_turned_off
from .settings import Endpoints, Options

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LaylaConfigEntry) -> bool:
    def keep(token: str) -> None:
        # Cognito handed out a new refresh token: keep it, or the next restart signs in with a dead one
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_REFRESH_TOKEN: token})

    api = LaylaApi(
        async_get_clientsession(hass),
        entry.data[CONF_REFRESH_TOKEN],
        hass.async_add_executor_job,
        keep,
        endpoints=Endpoints.from_data(entry.data),
    )
    options = Options.from_options(entry.options)
    coordinator = LaylaCoordinator(hass, entry, api, options)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    remove_turned_off(hass, entry, options)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LaylaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: LaylaConfigEntry, device: dr.DeviceEntry) -> bool:
    """A device can be deleted by hand once Layla no longer reports it."""
    coordinator = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    current = data.devices if data else {}
    return not any(domain == DOMAIN and ident in current for domain, ident in device.identifiers)
