"""What the options remove from Home Assistant's registries, and which alarm sensors already exist.

Nothing is removed because of what Layla's answer happens to leave out: a property that fails to answer, or a
device missing for a moment, would otherwise take its entities (and their names, areas and history) with it.
Things are removed only because the options say so."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN
from .model import ALARMS, READINGS, Device
from .settings import Options

# The last part of each entity's unique id ("<device id>_<key>")
_KEYS = sorted({*READINGS, *ALARMS, "active_alarms", "online"}, key=len, reverse=True)


def split_unique_id(unique_id: str) -> tuple[str, str] | None:
    """An entity's unique id → (device id, key), or None if it isn't one of ours."""
    for key in _KEYS:
        if unique_id.endswith("_" + key):
            return unique_id[: -len(key) - 1], key
    return None


def _ours(hass: HomeAssistant, entry: ConfigEntry):
    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        split = split_unique_id(ent.unique_id)
        if split is not None:
            yield ent_reg, ent, *split


@callback
def existing_alarms(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, set[str]]:
    """The alarm sensors this entry already has, by device id. With the device's own alarms turned on, these stay
    (off while the alarm isn't active), so one created because an alarm fired keeps its name, area and history."""
    out: dict[str, set[str]] = {}
    for _reg, _ent, device_id, key in _ours(hass, entry):
        if key in ALARMS:
            out.setdefault(device_id, set()).add(key)
    return out


@callback
def remove_turned_off(hass: HomeAssistant, entry: ConfigEntry, options: Options) -> None:
    """At setup: remove the readings the options turn off and, when only the chosen alarms are wanted, the other
    alarms' sensors."""
    for ent_reg, ent, _device_id, key in list(_ours(hass, entry)):
        if (key in READINGS and key not in options.readings) or (
            key in ALARMS and not options.device_alarms and key not in options.alarms
        ):
            ent_reg.async_remove(ent.entity_id)


@callback
def remove_for_new_options(
    hass: HomeAssistant, entry: ConfigEntry, old: Options, new: Options, devices: dict[str, Device] | None
) -> None:
    """When the options form is saved: remove the sensors of alarms taken off the always-created list (unless the
    device's own alarms are wanted and the device has that alarm turned on in Layla or active now), and the devices
    of properties no longer chosen. devices: what Layla reported last, or None when the integration isn't running
    (then a property's devices can't be told apart, and they're left for removing by hand)."""
    dropped = set(old.alarms) - set(new.alarms)
    if dropped:
        for ent_reg, ent, device_id, key in list(_ours(hass, entry)):
            if key not in dropped:
                continue
            d = (devices or {}).get(device_id)
            if new.device_alarms and d is not None and key in d.configured_alarms | set(d.firing):
                continue
            ent_reg.async_remove(ent.entity_id)
    if new.properties and devices:
        dev_reg = dr.async_get(hass)
        leaving = {d.id for d in devices.values() if d.property_id and d.property_id not in new.properties}
        for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if any(domain == DOMAIN and ident in leaving for domain, ident in dev.identifiers):
                dev_reg.async_update_device(dev.id, remove_config_entry_id=entry.entry_id)
