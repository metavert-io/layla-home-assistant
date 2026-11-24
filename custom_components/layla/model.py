"""Layla's API answers as plain data. No Home Assistant imports, so it's tested on its own."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Without a connection status, a device that reported this recently counts as online (the default; it's an option).
RECENT = timedelta(minutes=60)

# The readings Layla reports (its MeasureName), with how they're shown. The outdoor_* readings
# are the weather where the property is; they're left out (Home Assistant has weather).
READINGS: dict[str, dict[str, Any]] = {
    "noise": {"name": "Noise", "unit": "dB", "device_class": "sound_pressure"},
    "occupancy_min": {"name": "People (low estimate)", "unit": None, "device_class": None, "icon": "mdi:account-group"},
    "occupancy_max": {"name": "People (high estimate)", "unit": None, "device_class": None, "icon": "mdi:account-group"},
    "temperature": {"name": "Temperature", "unit": "temperature", "device_class": "temperature"},
    "humidity": {"name": "Humidity", "unit": "%", "device_class": "humidity"},
    "aq_iaq": {"name": "Air quality index", "unit": None, "device_class": "aqi"},
    "aq_tvoc_ppb": {"name": "VOCs", "unit": "ppb", "device_class": "volatile_organic_compounds_parts"},
    "mold_risk_index": {"name": "Mold risk", "unit": None, "device_class": None, "icon": "mdi:mushroom"},
    "power": {"name": "Power", "unit": "W", "device_class": "power"},
    "wifi_rssi": {"name": "Wi-Fi signal", "unit": "dBm", "device_class": "signal_strength", "diagnostic": True},
    "net_qlt": {"name": "Network quality", "unit": None, "device_class": None, "diagnostic": True, "icon": "mdi:wifi"},
}

# Layla's alarms (its AlarmName), each an on/off sensor: on while it's active, snoozed or not.
ALARMS: dict[str, dict[str, Any]] = {
    "smoke_alarm": {"name": "Smoke", "device_class": "smoke"},
    "co_alarm": {"name": "Carbon monoxide", "device_class": "carbon_monoxide"},
    "noise_alarm": {"name": "Noise alarm", "device_class": "sound"},
    "noise_alarm_quiet_hours": {"name": "Quiet-hours noise", "device_class": "sound"},
    "occupancy_alarm": {"name": "Too many people", "device_class": "problem"},
    "security_alarm": {"name": "Security alarm", "device_class": "safety"},
    "air_quality_alarm": {"name": "Air quality alarm", "device_class": "problem"},
    "co2_alarm": {"name": "CO2 alarm", "device_class": "problem"},
    "tvoc_alarm": {"name": "VOC alarm", "device_class": "problem"},
    "bvoc_alarm": {"name": "Breath VOC alarm", "device_class": "problem"},
    "mold_alarm": {"name": "Mold alarm", "device_class": "problem"},
    "party_detection": {"name": "Party detected", "device_class": "problem"},
}
# Always offered, whatever the device's alarm settings say: the ones that matter most.
CORE_ALARMS = ("smoke_alarm", "co_alarm", "noise_alarm", "occupancy_alarm", "security_alarm")

MODELS = {"v3.0": "Layla 3.0", "SP": "Layla Sensor Pro", "EM": "Layla EM"}


def alarm_name(name: str) -> str:
    """An alarm's name without the _start/_end of its notification type."""
    for suffix in ("_start", "_end"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


@dataclass
class Device:
    """One Layla sensor, as the API last described it."""

    id: str
    name: str
    mac: str = ""
    serial: str = ""
    model: str = ""
    property_id: str = ""
    property_name: str = ""
    online: bool = False
    updated_at: str = ""
    pillar: str = ""
    readings: dict[str, float] = field(default_factory=dict)
    reading_range: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    reading_at: dict[str, str] = field(default_factory=dict)
    firing: dict[str, str] = field(default_factory=dict)  # active alarm (snoozed too) -> since (ISO time)
    snoozed: set[str] = field(default_factory=set)  # the active alarms whose notifications are snoozed in Layla
    configured_alarms: set[str] = field(default_factory=set)

    def alarms_offered(self, always: Iterable[str] = CORE_ALARMS, from_device: bool = True) -> list[str]:
        """The alarms this device gets an on/off sensor for: the ones always offered, and (from_device) the ones
        turned on in the device's Layla settings or active now."""
        names = set(always)
        if from_device:
            names |= self.configured_alarms | set(self.firing)
        return [a for a in ALARMS if a in names]

    def title(self, with_property: bool = False) -> str:
        """The device's name, after its property's name when asked (for accounts with several properties)."""
        if with_property and self.property_name and not self.name.startswith(self.property_name):
            return f"{self.property_name} {self.name}"
        return self.name


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _zone(name: Any) -> tzinfo:
    try:
        return ZoneInfo(name) if isinstance(name, str) and name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


# A device's clock may run a little ahead of ours
_SKEW = timedelta(minutes=5)


def _when(s: Any, zone: tzinfo = UTC, now: datetime | None = None) -> datetime | None:
    """An ISO-8601 time; one without a zone is the property's wall clock (zone). In the hour that repeats when the
    clocks go back, a wall-clock time happened twice: it's taken as the later of the two that isn't after now."""
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo:
        return t
    # in UTC, so the two readings compare by the instant they stand for (same-zone comparisons ignore fold)
    first, second = (t.replace(tzinfo=zone, fold=f).astimezone(UTC) for f in (0, 1))
    if now is not None and second > now + _SKEW:
        return first
    return max(first, second)


def parse_devices(body: Any, now: datetime | None = None, recent: timedelta = RECENT) -> dict[str, Device]:
    """Devices as GET /v1/devices?property_id=… lists them, with the optional sections Layla's web app asks for
    (and the property's time zone and name, added by api.py) → the devices by id. Entries without an id are
    skipped. Without a connection status, a device is online when it reported within `recent`."""
    now = now or datetime.now(UTC)
    out: dict[str, Device] = {}
    if not isinstance(body, list):
        return out
    for d in body:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        dev = Device(
            id=str(d["id"]),
            name=(d.get("name") or "").strip() or "Layla",
            mac=d.get("device_mac") or "",
            serial=d.get("serial_number") or "",
            model=MODELS.get(d.get("category") or "", "Layla"),
            property_id=str(d.get("property_id") or ""),
            property_name=str(d.get("_property_name") or "").strip(),
            online=d.get("connection_status") == "online",
            updated_at=d.get("last_updated_at") or "",
            pillar=d.get("device_pillar") or d.get("mode") or "",
        )
        if not isinstance(dev.pillar, str):
            dev.pillar = ""
        for v in d.get("latest_values") or []:
            if not isinstance(v, dict) or v.get("name") not in READINGS:
                continue
            x = _num(v.get("value"))
            if x is None:
                continue
            dev.readings[v["name"]] = x
            low, high = _num(v.get("min_value")), _num(v.get("max_value"))
            if not (low in (None, 0) and high in (None, 0)):  # (Layla sends 0 and 0 when it has no range)
                dev.reading_range[v["name"]] = (low, high)
            dev.reading_at[v["name"]] = v.get("timestamp") or ""
        active = d.get("active_alarms")
        if isinstance(active, list):
            for a in active:
                if not isinstance(a, dict) or not a.get("name"):
                    continue
                n = alarm_name(a["name"])
                # a snoozed alarm is still active (only Layla's notifications are muted): it stays on
                dev.firing[n] = a.get("first_datapoint_timestamp") or ""
                if a.get("state") == "snoozed":
                    dev.snoozed.add(n)
        else:  # older answers: names only
            for n in d.get("in_alarm") or []:
                dev.firing[alarm_name(str(n))] = ""
            for n in d.get("snoozed") or []:
                dev.firing.setdefault(alarm_name(str(n)), "")
                dev.snoozed.add(alarm_name(str(n)))
        for a in d.get("alarms") or []:
            if isinstance(a, dict) and a.get("name") and a.get("enabled", True):
                dev.configured_alarms.add(alarm_name(a["name"]))
        if "connection_status" not in d:
            # no status in the answer: online if it reported recently
            zone = _zone(d.get("_timezone"))
            times = [t for t in (_when(x, zone, now) for x in [dev.updated_at, *dev.reading_at.values()]) if t]
            dev.online = bool(times) and now - max(times) <= recent
            if not dev.updated_at and times:
                dev.updated_at = max(times).isoformat()
        out[dev.id] = dev
    return out


def temperature_unit(user: Any) -> str:
    """The user's temperature unit from GET /v1/users/self: "C" or "F" (F when it doesn't say)."""
    if isinstance(user, dict):
        u = ((user.get("preferences") or {}).get("temperature_unit") or "").upper()
        if u in ("C", "F"):
            return u
    return "F"


def token_claims(token: str) -> dict[str, Any]:
    """A JWT's claims, unverified (only to read when it expires and whose it is)."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part))
        return claims if isinstance(claims, dict) else {}
    except (IndexError, ValueError):
        return {}
