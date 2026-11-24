"""Sign in to Layla: email and password, used once; only the refresh token is stored. The options choose what's
fetched and which entities are created."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import LaylaApi, LaylaApiError
from .auth import LaylaAuthError, LaylaConnectError, LaylaEndpointError, LaylaMfaError, Tokens, sign_in
from .const import (
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
    ONLINE_MINUTES_RANGE,
    UPDATE_MINUTES_RANGE,
)
from .model import ALARMS, READINGS
from .registry import remove_for_new_options
from .settings import Endpoints, Options

_LOGGER = logging.getLogger(__name__)

_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d+$")
_ENDPOINT_FIELDS = (CONF_API_URL, CONF_REGION, CONF_USER_POOL_ID, CONF_CLIENT_ID)
# The sign-in form's collapsed section with where to sign in
ADVANCED = "advanced"


def _endpoints_from(user_input: Mapping[str, Any]) -> tuple[Endpoints, dict[str, str]]:
    """The endpoints from the form's advanced section (the defaults for anything left out), and any error."""
    default = Endpoints()
    e = Endpoints(
        api_url=str(user_input.get(CONF_API_URL) or default.api_url).strip().rstrip("/"),
        region=str(user_input.get(CONF_REGION) or default.region).strip(),
        user_pool_id=str(user_input.get(CONF_USER_POOL_ID) or default.user_pool_id).strip(),
        client_id=str(user_input.get(CONF_CLIENT_ID) or default.client_id).strip(),
    )
    if not e.api_url.startswith("https://"):
        return e, {"base": "invalid_api_url"}
    if not _REGION.match(e.region):
        return e, {"base": "invalid_region"}
    if not e.user_pool_id.startswith(e.region + "_"):
        return e, {"base": "invalid_user_pool_id"}
    return e, {}


class LaylaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LaylaOptionsFlow:
        return LaylaOptionsFlow()

    async def _sign_in(self, email: str, password: str, endpoints: Endpoints) -> tuple[Tokens | None, dict[str, str]]:
        try:
            tokens = await self.hass.async_add_executor_job(sign_in, email, password, endpoints)
            api = LaylaApi(
                async_get_clientsession(self.hass),
                tokens.refresh_token,
                self.hass.async_add_executor_job,
                lambda _t: None,
                tokens,
                endpoints,
            )
            await api.user()  # the API takes the session
        except LaylaMfaError:
            return None, {"base": "mfa"}
        except LaylaAuthError:
            return None, {"base": "invalid_auth"}
        except LaylaEndpointError as err:
            _LOGGER.warning("Layla sign-in: %s", err)
            return None, {"base": "invalid_endpoints"}
        except (LaylaConnectError, LaylaApiError) as err:
            _LOGGER.warning("Layla sign-in: %s", err)
            return None, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001 — shown as "unknown", logged for a fix
            _LOGGER.exception("Layla sign-in failed")
            return None, {"base": "unknown"}
        if not tokens.refresh_token or not tokens.user_id:
            return None, {"base": "unknown"}
        return tokens, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            endpoints, errors = _endpoints_from(user_input.get(ADVANCED) or {})
            if not errors:
                email = user_input[CONF_EMAIL].strip()
                tokens, errors = await self._sign_in(email, user_input[CONF_PASSWORD], endpoints)
                if tokens:
                    await self.async_set_unique_id(tokens.user_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Layla ({email})",
                        data={CONF_EMAIL: email, CONF_REFRESH_TOKEN: tokens.refresh_token, **endpoints.changed()},
                    )
        default = Endpoints()
        advanced = vol.Schema({vol.Optional(key, default=getattr(default, key)): str for key in _ENDPOINT_FIELDS})
        fields = {
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(ADVANCED, default={}): section(advanced, {"collapsed": True}),
        }
        suggested = {k: v for k, v in (user_input or {}).items() if k != CONF_PASSWORD}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, errors = await self._sign_in(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD], Endpoints.from_data(entry.data))
            if tokens:
                await self.async_set_unique_id(tokens.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_REFRESH_TOKEN: tokens.refresh_token})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


def _minutes_selector(bounds: tuple[int, int]) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=bounds[0], max=bounds[1], step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
    )


def _choose(options: Mapping[str, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=k, label=v) for k, v in options.items()],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


class LaylaOptionsFlow(OptionsFlowWithReload):
    """What to fetch and which entities to create. Saving reloads the integration."""

    _listed_properties = False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = Options.from_options(self.config_entry.options)
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if user_input is not None:
            if not self._listed_properties:  # the form couldn't offer them: keep the choice as it was
                user_input = {**user_input, CONF_PROPERTIES: sorted(current.properties)}
            cleaned = _clean(user_input)
            devices = coordinator.data.devices if coordinator and coordinator.data else None
            remove_for_new_options(self.hass, self.config_entry, current, Options.from_options(cleaned), devices)
            return self.async_create_entry(data=cleaned)
        # the account's properties are only known while the integration is running
        known = dict(coordinator.data.properties) if coordinator and coordinator.data else {}
        self._listed_properties = bool(known)
        if known:
            for pid in current.properties:  # chosen before, gone from the account since
                known.setdefault(pid, pid)

        fields: dict[Any, Any] = {
            vol.Required(CONF_UPDATE_MINUTES): _minutes_selector(UPDATE_MINUTES_RANGE),
            vol.Required(CONF_ONLINE_MINUTES): _minutes_selector(ONLINE_MINUTES_RANGE),
        }
        if known:
            fields[vol.Optional(CONF_PROPERTIES)] = _choose(dict(sorted(known.items(), key=lambda kv: kv[1].lower())))
        fields |= {
            vol.Required(CONF_PROPERTY_IN_NAME): BooleanSelector(),
            vol.Optional(CONF_READINGS): _choose({k: v["name"] for k, v in READINGS.items()}),
            vol.Optional(CONF_ALARMS): _choose({k: v["name"] for k, v in ALARMS.items()}),
            vol.Required(CONF_DEVICE_ALARMS): BooleanSelector(),
        }
        suggested = {
            CONF_UPDATE_MINUTES: current.update_minutes,
            CONF_ONLINE_MINUTES: current.online_minutes,
            CONF_PROPERTIES: sorted(current.properties),
            CONF_PROPERTY_IN_NAME: current.property_in_name,
            CONF_READINGS: list(current.readings),
            CONF_ALARMS: list(current.alarms),
            CONF_DEVICE_ALARMS: current.device_alarms,
        }
        return self.async_show_form(step_id="init", data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), suggested))


def _clean(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The form's answer as options: whole minutes, and lists of known keys (a property list that's left out or
    empty means every property)."""
    return {
        CONF_UPDATE_MINUTES: int(user_input[CONF_UPDATE_MINUTES]),
        CONF_ONLINE_MINUTES: int(user_input[CONF_ONLINE_MINUTES]),
        CONF_PROPERTIES: [str(p) for p in user_input.get(CONF_PROPERTIES) or []],
        CONF_PROPERTY_IN_NAME: bool(user_input.get(CONF_PROPERTY_IN_NAME)),
        CONF_READINGS: [k for k in READINGS if k in (user_input.get(CONF_READINGS) or [])],
        CONF_ALARMS: [k for k in ALARMS if k in (user_input.get(CONF_ALARMS) or [])],
        CONF_DEVICE_ALARMS: bool(user_input.get(CONF_DEVICE_ALARMS)),
    }
