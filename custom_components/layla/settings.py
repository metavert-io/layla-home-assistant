"""Where to reach Layla, and the user's options, from a config entry's data and options (no Home Assistant
imports, so it's tested on its own). Anything missing or out of range falls back to the default."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CONF_ALARMS,
    CONF_API_URL,
    CONF_CLIENT_ID,
    CONF_DEVICE_ALARMS,
    CONF_ONLINE_MINUTES,
    CONF_PROPERTIES,
    CONF_PROPERTY_IN_NAME,
    CONF_READINGS,
    CONF_REGION,
    CONF_UPDATE_MINUTES,
    CONF_USER_POOL_ID,
    DEFAULT_API_URL,
    DEFAULT_CLIENT_ID,
    DEFAULT_ONLINE_MINUTES,
    DEFAULT_REGION,
    DEFAULT_UPDATE_MINUTES,
    DEFAULT_USER_POOL_ID,
    ONLINE_MINUTES_RANGE,
    UPDATE_MINUTES_RANGE,
)
from .model import ALARMS, CORE_ALARMS, READINGS


@dataclass(frozen=True)
class Endpoints:
    """Layla's API and sign-in service. The defaults are the ones Layla's own web app uses."""

    api_url: str = DEFAULT_API_URL
    region: str = DEFAULT_REGION
    user_pool_id: str = DEFAULT_USER_POOL_ID
    client_id: str = DEFAULT_CLIENT_ID

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> Endpoints:
        return cls(
            api_url=(data.get(CONF_API_URL) or DEFAULT_API_URL).rstrip("/"),
            region=data.get(CONF_REGION) or DEFAULT_REGION,
            user_pool_id=data.get(CONF_USER_POOL_ID) or DEFAULT_USER_POOL_ID,
            client_id=data.get(CONF_CLIENT_ID) or DEFAULT_CLIENT_ID,
        )

    def changed(self) -> dict[str, str]:
        """Only the values that differ from the defaults, as config entry data. Defaults aren't stored, so a
        future release can update them for everyone who never changed them."""
        default = Endpoints()
        out = {}
        for key, mine, theirs in (
            (CONF_API_URL, self.api_url, default.api_url),
            (CONF_REGION, self.region, default.region),
            (CONF_USER_POOL_ID, self.user_pool_id, default.user_pool_id),
            (CONF_CLIENT_ID, self.client_id, default.client_id),
        ):
            if mine != theirs:
                out[key] = mine
        return out


def _minutes(value: Any, default: int, bounds: tuple[int, int]) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(n, bounds[0]), bounds[1])


def _known(value: Any, known: Mapping[str, Any], default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return default
    chosen = {str(v) for v in value}
    return tuple(k for k in known if k in chosen)


@dataclass(frozen=True)
class Options:
    """What the integration fetches and which entities it creates."""

    update_minutes: int = DEFAULT_UPDATE_MINUTES
    online_minutes: int = DEFAULT_ONLINE_MINUTES
    properties: frozenset[str] = frozenset()  # empty: every property, including ones added later
    property_in_name: bool = False
    readings: tuple[str, ...] = field(default_factory=lambda: tuple(READINGS))
    alarms: tuple[str, ...] = CORE_ALARMS
    device_alarms: bool = True  # also the alarms turned on for the device in Layla, and any that fire

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Options:
        props = options.get(CONF_PROPERTIES)
        return cls(
            update_minutes=_minutes(options.get(CONF_UPDATE_MINUTES), DEFAULT_UPDATE_MINUTES, UPDATE_MINUTES_RANGE),
            online_minutes=_minutes(options.get(CONF_ONLINE_MINUTES), DEFAULT_ONLINE_MINUTES, ONLINE_MINUTES_RANGE),
            properties=frozenset(str(p) for p in props) if isinstance(props, (list, tuple, set)) else frozenset(),
            property_in_name=bool(options.get(CONF_PROPERTY_IN_NAME, False)),
            readings=_known(options.get(CONF_READINGS), READINGS, tuple(READINGS)),
            alarms=_known(options.get(CONF_ALARMS), ALARMS, CORE_ALARMS),
            device_alarms=bool(options.get(CONF_DEVICE_ALARMS, True)),
        )

    def wants_property(self, property_id: str) -> bool:
        return not self.properties or property_id in self.properties
