"""Setting up the integration against an invented API answer: the entities, the options, and what happens when
Layla ends the session or can't be reached."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.layla import async_remove_config_entry_device
from custom_components.layla.api import DEVICE_FIELDS
from custom_components.layla.auth import LaylaAuthError
from custom_components.layla.const import (
    CONF_ALARMS,
    CONF_DEVICE_ALARMS,
    CONF_ONLINE_MINUTES,
    CONF_PROPERTIES,
    CONF_PROPERTY_IN_NAME,
    CONF_READINGS,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_MINUTES,
    DEFAULT_API_URL,
    DOMAIN,
)
from custom_components.layla.diagnostics import async_get_config_entry_diagnostics
from custom_components.layla.model import CORE_ALARMS
from custom_components.layla.settings import Options

from .conftest import EMAIL, REFRESH_TOKEN, config_entry, devices_a, devices_b, mock_layla, properties, set_up, tokens


@pytest.fixture(autouse=True)
def _refresh(mock_refresh):
    yield mock_refresh


async def test_readings(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.LOADED

    noise = hass.states.get("sensor.living_room_noise")
    assert noise.state == "48.5"
    assert noise.attributes["unit_of_measurement"] == "dB"
    assert noise.attributes["low"] == 31.0
    assert noise.attributes["high"] == 66.0
    assert noise.attributes["layla_reading"] == "noise"
    assert noise.attributes["layla_device"] == "dev-a1"
    assert noise.attributes["measured_at"]

    people = hass.states.get("sensor.living_room_people_low_estimate")
    assert people.state == "2.0"
    assert "low" not in people.attributes  # Layla sends 0/0 when there's no range

    temperature = hass.states.get("sensor.living_room_temperature")
    assert temperature.state == "21.5"
    assert temperature.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS

    assert hass.states.get("sensor.living_room_humidity").state == "44.0"
    assert hass.states.get("sensor.living_room_air_quality_index").state == "52.0"
    assert hass.states.get("sensor.living_room_wi_fi_signal").state == "-61.0"
    # the outdoor weather isn't a reading of the room
    assert not any("outdoor" in s.entity_id for s in hass.states.async_all())


async def test_fahrenheit_account(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock, unit="F")
    await set_up(hass, config_entry())
    # Layla sent 21.5 °F; Home Assistant (metric here) shows it in °C
    temperature = hass.states.get("sensor.living_room_temperature")
    assert temperature.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS
    assert float(temperature.state) == pytest.approx((21.5 - 32) * 5 / 9, abs=0.1)


async def test_alarms(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    await set_up(hass, config_entry())

    firing = hass.states.get("binary_sensor.living_room_noise_alarm")
    assert firing.state == STATE_ON
    assert firing.attributes["since"] == "2026-01-02T22:15:00"
    assert firing.attributes["layla_alarm"] == "noise_alarm"
    assert "snoozed" not in firing.attributes
    for quiet in ("smoke", "carbon_monoxide", "too_many_people", "security_alarm", "party_detected"):
        assert hass.states.get(f"binary_sensor.living_room_{quiet}").state == STATE_OFF, quiet
    # turned off for the device: no sensor
    assert hass.states.get("binary_sensor.living_room_co2_alarm") is None
    # snoozed in Layla: still active, so on, and it says it's snoozed
    snoozed = hass.states.get("binary_sensor.living_room_mold_alarm")
    assert snoozed.state == STATE_ON
    assert snoozed.attributes["snoozed"] is True

    active = hass.states.get("sensor.living_room_active_alarms")
    assert active.state == "2"
    assert active.attributes["layla_alarms"] == ["mold_alarm", "noise_alarm"]
    assert active.attributes["labels"] == ["Mold alarm", "Noise alarm"]
    assert active.attributes["snoozed"] == ["mold_alarm"]


async def test_online(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    await set_up(hass, config_entry())
    assert hass.states.get("binary_sensor.living_room_online").state == STATE_ON
    # three hours since the bedroom's last report: offline, and its readings unavailable
    assert hass.states.get("binary_sensor.bedroom_online").state == STATE_OFF
    assert hass.states.get("sensor.bedroom_noise").state == STATE_UNAVAILABLE


async def test_online_window_option(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    await set_up(hass, config_entry({"online_minutes": 240}))
    assert hass.states.get("binary_sensor.bedroom_online").state == STATE_ON
    assert hass.states.get("sensor.bedroom_noise").state == "35.0"


async def test_device(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, device_registry: dr.DeviceRegistry) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    device = device_registry.async_get_device_by_identifier((DOMAIN, "dev-a1"), entry.entry_id)
    assert device.name == "Living room"
    assert device.manufacturer == "LaylaElectric"
    assert device.model == "Layla 3.0"
    assert device.serial_number == "SN-TEST-A1"
    assert (dr.CONNECTION_NETWORK_MAC, "02:00:00:00:00:a1") in device.connections
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-b1"), entry.entry_id).model == "Layla Sensor Pro"


async def test_property_in_name(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, device_registry: dr.DeviceRegistry) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry({CONF_PROPERTY_IN_NAME: True}))
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-a1"), entry.entry_id).name == "Seaside Cottage Living room"


async def test_only_chosen_properties(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    await set_up(hass, config_entry({CONF_PROPERTIES: ["prop-a"]}))
    assert hass.states.get("sensor.living_room_noise") is not None
    assert hass.states.get("sensor.bedroom_noise") is None
    asked = [str(url) for _method, url, _data, _headers in aioclient_mock.mock_calls]
    assert not any("prop-b" in u for u in asked)


async def test_chosen_readings_and_alarms(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    options = {CONF_READINGS: ["noise"], CONF_ALARMS: ["smoke_alarm"], CONF_DEVICE_ALARMS: False}
    await set_up(hass, config_entry(options))
    sensors = {s.entity_id for s in hass.states.async_all("sensor") if s.entity_id.startswith("sensor.living_room")}
    assert sensors == {"sensor.living_room_noise", "sensor.living_room_active_alarms"}
    binaries = {s.entity_id for s in hass.states.async_all("binary_sensor") if s.entity_id.startswith("binary_sensor.living_room")}
    assert binaries == {"binary_sensor.living_room_smoke", "binary_sensor.living_room_online"}
    # the count still includes alarms without a sensor of their own (noise, and mold while snoozed)
    assert hass.states.get("sensor.living_room_active_alarms").state == "2"


async def test_changing_options_removes_entities_and_devices(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    assert entity_registry.async_get("sensor.living_room_humidity") is not None
    assert entity_registry.async_get("binary_sensor.living_room_party_detected") is not None

    await save_options(hass, entry, {CONF_PROPERTIES: ["prop-a"], CONF_READINGS: ["noise", "temperature"], CONF_DEVICE_ALARMS: False})

    assert entity_registry.async_get("sensor.living_room_humidity") is None
    assert entity_registry.async_get("sensor.living_room_noise") is not None
    assert entity_registry.async_get("binary_sensor.living_room_party_detected") is None
    assert entity_registry.async_get("binary_sensor.living_room_smoke") is not None
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-b1"), entry.entry_id) is None
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-a1"), entry.entry_id) is not None


async def test_unticked_alarm_is_removed_unless_the_device_has_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entity_registry: er.EntityRegistry
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    # security: only there because it's always created; noise: also active on the device
    keep = [a for a in CORE_ALARMS if a not in ("security_alarm", "noise_alarm")]
    await save_options(hass, entry, {CONF_ALARMS: keep})
    assert entity_registry.async_get("binary_sensor.living_room_security_alarm") is None
    assert entity_registry.async_get("binary_sensor.bedroom_security_alarm") is None
    assert hass.states.get("binary_sensor.living_room_noise_alarm").state == STATE_ON
    assert entity_registry.async_get("binary_sensor.bedroom_noise_alarm") is None


async def test_alarm_sensor_stays_after_its_alarm_stops(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entity_registry: er.EntityRegistry
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    entity_registry.async_update_entity("binary_sensor.living_room_mold_alarm", name="Bathroom mold")

    quiet = devices_a()
    quiet[0]["active_alarms"] = []
    aioclient_mock.clear_requests()
    mock_layla(aioclient_mock, by_property={"prop-a": quiet, "prop-b": devices_b()})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    mold = entity_registry.async_get("binary_sensor.living_room_mold_alarm")
    assert mold is not None and mold.name == "Bathroom mold"
    assert hass.states.get("binary_sensor.living_room_mold_alarm").state == STATE_OFF


async def test_device_missing_for_a_moment_is_kept(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, device_registry: dr.DeviceRegistry
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry({CONF_PROPERTIES: ["prop-a"]}))
    aioclient_mock.clear_requests()
    mock_layla(aioclient_mock, by_property={"prop-a": []})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-a1"), entry.entry_id) is not None
    assert hass.states.get("sensor.living_room_noise").state == STATE_UNAVAILABLE


async def test_one_property_failing_leaves_the_others(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, device_registry: dr.DeviceRegistry
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    assert hass.states.get("sensor.bedroom_noise") is not None

    aioclient_mock.clear_requests()
    mock_layla(aioclient_mock, by_property={"prop-a": devices_a()})
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/devices", params={"property_id": "prop-b", "fields": DEVICE_FIELDS}, status=503)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.last_update_success
    assert entry.runtime_data.data.failed.keys() == {"prop-b"}
    assert hass.states.get("sensor.living_room_noise").state == "48.5"
    assert hass.states.get("sensor.bedroom_noise").state == STATE_UNAVAILABLE
    assert device_registry.async_get_device_by_identifier((DOMAIN, "dev-b1"), entry.entry_id) is not None


async def test_every_property_failing_fails_the_update(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock, by_property={})
    for pid in ("prop-a", "prop-b"):
        aioclient_mock.get(f"{DEFAULT_API_URL}/v1/devices", params={"property_id": pid, "fields": DEVICE_FIELDS}, status=503)
    entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_temperature_unit_follows_the_account(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock, unit="C")
    entry = await set_up(hass, config_entry())
    assert hass.states.get("sensor.living_room_temperature").state == "21.5"

    aioclient_mock.clear_requests()
    mock_layla(aioclient_mock, unit="F")  # changed in Layla: the next readings come in °F
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data.temperature_unit == "F"
    assert float(hass.states.get("sensor.living_room_temperature").state) == pytest.approx((21.5 - 32) * 5 / 9, abs=0.1)


async def test_custom_api_url(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock, api_url="https://layla.example.com/api")
    entry = await set_up(hass, config_entry(api_url="https://layla.example.com/api"))
    assert entry.state is ConfigEntryState.LOADED
    assert all(str(url).startswith("https://layla.example.com/api/") for _m, url, _d, _h in aioclient_mock.mock_calls)


async def test_ended_session_asks_to_sign_in_again(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    with patch("custom_components.layla.api.refresh", side_effect=LaylaAuthError("session ended")):
        entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_refused_token_twice_asks_to_sign_in_again(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/users/self", status=401)
    entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(aioclient_mock.mock_calls) == 2  # renewed once, then reported


async def test_layla_unreachable_retries(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/users/self", json={"preferences": {}})
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/properties", status=503)
    entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rotated_refresh_token_is_kept(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    with patch("custom_components.layla.api.refresh", side_effect=lambda token, endpoints=None: tokens("rotated-token")):
        entry = await set_up(hass, config_entry())
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated-token"


async def test_unload(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_device_only_when_gone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, device_registry: dr.DeviceRegistry
) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())
    current = device_registry.async_get_device_by_identifier((DOMAIN, "dev-a1"), entry.entry_id)
    assert not await async_remove_config_entry_device(hass, entry, current)
    gone = device_registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "dev-gone")})
    assert await async_remove_config_entry_device(hass, entry, gone)


async def test_diagnostics_leave_out_identifying_details(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(
        hass, config_entry({CONF_PROPERTIES: ["prop-a", "prop-b"]}, client_id="my-own-client", user_pool_id="eu-west-1_Mine")
    )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)
    for secret in (EMAIL, REFRESH_TOKEN, "my-own-client", "eu-west-1_Mine", "Living room", "Seaside Cottage", "dev-a1", "prop-a", "02:00:00:00:00:A1", "SN-TEST-A1"):
        assert secret not in text, secret
    assert diag["temperature_unit"] == "C"
    assert diag["state"] == "loaded"
    assert diag["properties_not_answering"] == 0
    assert diag["properties"] == len(properties())
    assert len(diag["devices"]) == 2
    assert diag["devices"][0]["readings"]["noise"] == devices_a()[0]["latest_values"][0]["value"]


async def test_diagnostics_when_setup_failed(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/users/self", json={"preferences": {}})
    aioclient_mock.get(f"{DEFAULT_API_URL}/v1/properties", status=503)
    entry = await set_up(hass, config_entry())
    assert entry.state is ConfigEntryState.SETUP_RETRY
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["state"] == "setup_retry"
    assert diag["devices"] == []
    assert EMAIL not in json.dumps(diag)


async def save_options(hass: HomeAssistant, entry, changes: dict) -> None:
    """Saves the options form with these answers changed (the rest as they were)."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    current = Options.from_options(entry.options)
    answer = {
        CONF_UPDATE_MINUTES: current.update_minutes,
        CONF_ONLINE_MINUTES: current.online_minutes,
        CONF_PROPERTIES: sorted(current.properties),
        CONF_PROPERTY_IN_NAME: current.property_in_name,
        CONF_READINGS: list(current.readings),
        CONF_ALARMS: list(current.alarms),
        CONF_DEVICE_ALARMS: current.device_alarms,
        **changes,
    }
    await hass.config_entries.options.async_configure(result["flow_id"], answer)
    await hass.async_block_till_done()
