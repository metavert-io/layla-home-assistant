"""Signing in (with sign-in faked), reauth, and the options form."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.layla.api import LaylaApiError
from custom_components.layla.auth import LaylaAuthError, LaylaConnectError, LaylaEndpointError, LaylaMfaError
from custom_components.layla.const import (
    CONF_ALARMS,
    CONF_API_URL,
    CONF_CLIENT_ID,
    CONF_DEVICE_ALARMS,
    CONF_ONLINE_MINUTES,
    CONF_PROPERTIES,
    CONF_PROPERTY_IN_NAME,
    CONF_READINGS,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    CONF_UPDATE_MINUTES,
    CONF_USER_POOL_ID,
    DOMAIN,
)
from custom_components.layla.config_flow import ADVANCED
from custom_components.layla.settings import Endpoints

from .conftest import EMAIL, USER_ID, config_entry, mock_layla, set_up, tokens

PASSWORD = "not-a-real-password"


@pytest.fixture
def sign_in() -> Generator[MagicMock]:
    with patch("custom_components.layla.config_flow.sign_in", return_value=tokens("new-refresh-token")) as m:
        yield m


@pytest.fixture
def api_user() -> Generator[AsyncMock]:
    with patch("custom_components.layla.config_flow.LaylaApi.user", return_value={"preferences": {}}) as m:
        yield m


@pytest.fixture
def no_setup() -> Generator[AsyncMock]:
    with patch("custom_components.layla.async_setup_entry", return_value=True) as m:
        yield m


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


def _advanced(**change: str) -> dict[str, str]:
    """The advanced section as the form sends it: the defaults, with any changes."""
    default = Endpoints()
    values = {CONF_API_URL: default.api_url, CONF_REGION: default.region, CONF_USER_POOL_ID: default.user_pool_id, CONF_CLIENT_ID: default.client_id}
    return {**values, **change}


async def test_sign_in(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert set(result["data_schema"].schema) == {CONF_EMAIL, CONF_PASSWORD, ADVANCED}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: f"  {EMAIL} ", CONF_PASSWORD: PASSWORD, ADVANCED: _advanced()}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Layla ({EMAIL})"
    assert result["data"] == {CONF_EMAIL: EMAIL, CONF_REFRESH_TOKEN: "new-refresh-token"}  # never the password
    assert result["result"].unique_id == USER_ID
    sign_in.assert_called_once_with(EMAIL, PASSWORD, Endpoints())
    assert no_setup.called


@pytest.mark.parametrize(
    ("error", "where", "expected"),
    [
        (LaylaAuthError("wrong password"), "sign_in", "invalid_auth"),
        (LaylaMfaError("second step"), "sign_in", "mfa"),
        (LaylaConnectError("no network"), "sign_in", "cannot_connect"),
        (LaylaEndpointError("no such client"), "sign_in", "invalid_endpoints"),
        (LaylaApiError("Layla answered 500"), "api", "cannot_connect"),
        (RuntimeError("surprise"), "sign_in", "unknown"),
    ],
)
async def test_sign_in_errors_then_recover(
    hass: HomeAssistant,
    sign_in: MagicMock,
    api_user: AsyncMock,
    no_setup: AsyncMock,
    error: Exception,
    where: str,
    expected: str,
) -> None:
    result = await _start(hass)
    (sign_in if where == "sign_in" else api_user).side_effect = error
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    sign_in.side_effect = None
    api_user.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_no_refresh_token_is_unknown(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock) -> None:
    sign_in.return_value = tokens("")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD})
    assert result["errors"] == {"base": "unknown"}


async def test_already_configured(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    config_entry().add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_advanced_endpoints(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    result = await _start(hass)
    advanced = result["data_schema"].schema[ADVANCED]
    assert advanced.options == {"collapsed": True}
    assert set(advanced.schema.schema) == {CONF_API_URL, CONF_REGION, CONF_USER_POOL_ID, CONF_CLIENT_ID}

    answer = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, ADVANCED: _advanced(client_id="a-client-of-my-own")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], answer)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # only what differs from the defaults is stored
    assert result["data"] == {CONF_EMAIL: EMAIL, CONF_REFRESH_TOKEN: "new-refresh-token", CONF_CLIENT_ID: "a-client-of-my-own"}
    assert sign_in.call_args.args[2] == Endpoints(client_id="a-client-of-my-own")


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({CONF_API_URL: "http://insecure.example.com"}, "invalid_api_url"),
        ({CONF_REGION: "not a region"}, "invalid_region"),
        ({CONF_USER_POOL_ID: "us-east-1_Abc"}, "invalid_user_pool_id"),
    ],
)
async def test_advanced_endpoints_checked(hass: HomeAssistant, sign_in: MagicMock, change: dict[str, str], error: str) -> None:
    result = await _start(hass)
    answer = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, ADVANCED: _advanced(**change)}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], answer)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    sign_in.assert_not_called()


async def test_advanced_section_left_out(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert sign_in.call_args.args[2] == Endpoints()


async def test_reauth(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    entry = config_entry(client_id="a-client-of-my-own")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["email"] == EMAIL

    sign_in.side_effect = LaylaAuthError("wrong password")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}

    sign_in.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh-token"
    assert entry.data[CONF_CLIENT_ID] == "a-client-of-my-own"
    sign_in.assert_called_with(EMAIL, PASSWORD, Endpoints(client_id="a-client-of-my-own"))


async def test_reauth_with_another_account(hass: HomeAssistant, sign_in: MagicMock, api_user: AsyncMock, no_setup: AsyncMock) -> None:
    entry = config_entry()
    entry.add_to_hass(hass)
    sign_in.return_value = tokens("other-refresh-token", user_id="someone-else")
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_REFRESH_TOKEN] != "other-refresh-token"


async def test_options(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_refresh: MagicMock) -> None:
    mock_layla(aioclient_mock)
    entry = await set_up(hass, config_entry())

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    assert CONF_PROPERTIES in schema  # listed from the running integration
    properties = schema[next(k for k in schema if k == CONF_PROPERTIES)].config["options"]
    assert [o["label"] for o in properties] == ["Mountain Cabin", "Seaside Cottage"]

    answer = {
        CONF_UPDATE_MINUTES: 5.0,
        CONF_ONLINE_MINUTES: 30.0,
        CONF_PROPERTIES: ["prop-a"],
        CONF_PROPERTY_IN_NAME: True,
        CONF_READINGS: ["temperature", "noise"],
        CONF_ALARMS: ["co_alarm", "smoke_alarm"],
        CONF_DEVICE_ALARMS: False,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], answer)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_UPDATE_MINUTES: 5,
        CONF_ONLINE_MINUTES: 30,
        CONF_PROPERTIES: ["prop-a"],
        CONF_PROPERTY_IN_NAME: True,
        CONF_READINGS: ["noise", "temperature"],
        CONF_ALARMS: ["smoke_alarm", "co_alarm"],
        CONF_DEVICE_ALARMS: False,
    }
    # reloaded with the new options
    assert entry.runtime_data.options.update_minutes == 5
    assert hass.states.get("sensor.bedroom_noise") is None


async def test_options_keep_properties_when_not_running(hass: HomeAssistant) -> None:
    entry = config_entry({CONF_PROPERTIES: ["prop-a"]})
    entry.add_to_hass(hass)  # not set up: the account's properties aren't known
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_PROPERTIES not in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UPDATE_MINUTES: 2, CONF_ONLINE_MINUTES: 60, CONF_PROPERTY_IN_NAME: False, CONF_DEVICE_ALARMS: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PROPERTIES] == ["prop-a"]
    assert entry.options[CONF_READINGS] == []  # left empty: no readings
