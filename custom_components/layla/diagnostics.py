"""Diagnostics for the Layla integration, with the account and the devices' identifiers redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_ID, CONF_PROPERTIES, CONF_REFRESH_TOKEN, CONF_USER_POOL_ID
from .coordinator import LaylaConfigEntry

# Anything that could identify the account, a device or a property: people paste diagnostics into public issues
REDACT = {
    CONF_EMAIL,
    CONF_REFRESH_TOKEN,
    CONF_PROPERTIES,
    CONF_CLIENT_ID,
    CONF_USER_POOL_ID,
    "mac",
    "serial",
    "id",
    "property_id",
    "name",
    "property_name",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: LaylaConfigEntry) -> dict[str, Any]:
    # not there when setting up failed (e.g. Layla couldn't be reached): the entry and options still help
    coordinator = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    devices = [{**asdict(d), "snoozed": sorted(d.snoozed), "configured_alarms": sorted(d.configured_alarms)} for d in data.devices.values()] if data else []
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": async_redact_data(dict(entry.options), REDACT),
        "state": entry.state.value,
        "last_update_success": coordinator.last_update_success if coordinator else None,
        "properties": len(data.properties) if data else None,
        "properties_not_answering": len(data.failed) if data else None,
        "temperature_unit": data.temperature_unit if data else None,
        "answer_shape": data.shape if data else None,
        "devices": [async_redact_data(d, REDACT) for d in devices],
    }
