"""Shared fixtures: an invented Layla account, with sign-in and Layla's API faked."""

from __future__ import annotations

import time
from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.layla.api import DEVICE_FIELDS
from custom_components.layla.auth import Tokens
from custom_components.layla.const import CONF_REFRESH_TOKEN, DEFAULT_API_URL, DOMAIN

EMAIL = "someone@example.com"
USER_ID = "user-0001"
REFRESH_TOKEN = "refresh-token-for-tests"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    yield


def tokens(refresh_token: str = REFRESH_TOKEN, user_id: str = USER_ID) -> Tokens:
    return Tokens("access-token-for-tests", refresh_token, time.time() + 3600, user_id)


@pytest.fixture
def mock_refresh() -> Generator[Any]:
    """Renewing the access token always works, with the same refresh token."""
    with patch("custom_components.layla.api.refresh", side_effect=lambda token, endpoints=None: tokens(token)) as m:
        yield m


def wall_clock(zone: str, ago: timedelta) -> str:
    """A time as Layla sends it: the property's local time, without a zone."""
    return (datetime.now(ZoneInfo(zone)) - ago).replace(tzinfo=None, microsecond=0).isoformat()


def properties() -> list[dict[str, Any]]:
    return [
        {"id": "prop-a", "name": "Seaside Cottage", "timezone": "Europe/Lisbon"},
        {"id": "prop-b", "name": "Mountain Cabin", "timezone": "America/Denver"},
    ]


def devices_a() -> list[dict[str, Any]]:
    """One device that reported a few minutes ago, with a noise alarm firing."""
    now = wall_clock("Europe/Lisbon", timedelta(minutes=3))
    return [
        {
            "id": "dev-a1",
            "property_id": "prop-a",
            "name": "Living room",
            "device_mac": "02:00:00:00:00:A1",
            "serial_number": "SN-TEST-A1",
            "category": "v3.0",
            "mode": "noise",
            "latest_values": [
                {"name": "noise", "value": 48.5, "min_value": 31, "max_value": 66, "timestamp": now},
                {"name": "occupancy_min", "value": 2, "min_value": 0, "max_value": 0, "timestamp": now},
                {"name": "occupancy_max", "value": 4, "min_value": 0, "max_value": 0, "timestamp": now},
                {"name": "temperature", "value": 21.5, "timestamp": now},
                {"name": "humidity", "value": 44, "timestamp": now},
                {"name": "aq_iaq", "value": 52, "timestamp": now},
                {"name": "wifi_rssi", "value": -61, "timestamp": now},
                {"name": "outdoor_temperature", "value": 9, "timestamp": now},
            ],
            "active_alarms": [
                {"name": "noise_alarm_start", "state": "in_alarm", "first_datapoint_timestamp": "2026-01-02T22:15:00"},
                {"name": "mold_alarm", "state": "snoozed"},
            ],
            "alarms": [{"name": "party_detection", "enabled": True}, {"name": "co2_alarm", "enabled": False}],
        }
    ]


def devices_b() -> list[dict[str, Any]]:
    """One device that last reported three hours ago."""
    then = wall_clock("America/Denver", timedelta(hours=3))
    return [
        {
            "id": "dev-b1",
            "property_id": "prop-b",
            "name": "Bedroom",
            "category": "SP",
            "latest_values": [{"name": "noise", "value": 35, "timestamp": then}],
            "active_alarms": [],
        }
    ]


def mock_layla(
    aioclient_mock: AiohttpClientMocker,
    *,
    unit: str = "C",
    props: list[dict[str, Any]] | None = None,
    by_property: dict[str, list[dict[str, Any]]] | None = None,
    api_url: str = DEFAULT_API_URL,
) -> None:
    """Layla's API answers for the invented account."""
    aioclient_mock.get(f"{api_url}/v1/users/self", json={"id": USER_ID, "preferences": {"temperature_unit": unit}})
    aioclient_mock.get(f"{api_url}/v1/properties", json=properties() if props is None else props)
    for pid, devs in (by_property if by_property is not None else {"prop-a": devices_a(), "prop-b": devices_b()}).items():
        aioclient_mock.get(
            f"{api_url}/v1/devices", params={"property_id": pid, "fields": DEVICE_FIELDS}, json={"data": devs}
        )


def config_entry(options: dict[str, Any] | None = None, **data: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Layla ({EMAIL})",
        unique_id=USER_ID,
        data={"email": EMAIL, CONF_REFRESH_TOKEN: REFRESH_TOKEN, **data},
        options=options or {},
    )


async def set_up(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
