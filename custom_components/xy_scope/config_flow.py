"""Set up a box (host, port, token), and map entities onto its inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ScopeAuthError, ScopeClient, ScopeConnectionError, ScopeVersionError
from .const import (
    DEFAULT_PORT,
    DOMAIN,
    LOGGER,
    OPT_BIRTHDAYS,
    OPT_CAR_A,
    OPT_CAR_B,
    OPT_HIGH_TEMP,
    OPT_INSIDE_TEMP,
    OPT_LOW_TEMP,
    OPT_OUTSIDE_TEMP,
    OPT_PLANT_A,
    OPT_PLANT_B,
    OPT_POWER,
    OPT_WEATHER,
)
from .suggest import suggest_options

_TEMP = EntitySelector(EntitySelectorConfig(
    domain=["sensor", "weather", "input_number"]))
_SELECTORS = {
    OPT_INSIDE_TEMP: _TEMP,
    OPT_OUTSIDE_TEMP: _TEMP,
    OPT_HIGH_TEMP: _TEMP,
    OPT_LOW_TEMP: _TEMP,
    OPT_WEATHER: EntitySelector(EntitySelectorConfig(domain="weather")),
    OPT_PLANT_A: EntitySelector(EntitySelectorConfig(domain="sensor")),
    OPT_PLANT_B: EntitySelector(EntitySelectorConfig(domain="sensor")),
    OPT_CAR_A: EntitySelector(EntitySelectorConfig(
        domain=["sensor", "device_tracker", "person"])),
    OPT_CAR_B: EntitySelector(EntitySelectorConfig(
        domain=["sensor", "device_tracker", "person"])),
    OPT_BIRTHDAYS: EntitySelector(EntitySelectorConfig(domain="sensor")),
    OPT_POWER: EntitySelector(EntitySelectorConfig(domain=["switch", "light"])),
}


def _box_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)):
            cv.port,
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    })


async def _validate(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Errors for the form, empty when the box answers and takes the token."""
    client = ScopeClient(async_get_clientsession(hass), data[CONF_HOST],
                         data[CONF_PORT], data[CONF_TOKEN])
    try:
        await client.status()
        await client.check_token()
    except ScopeConnectionError:
        return {"base": "cannot_connect"}
    except ScopeAuthError:
        return {"base": "invalid_auth"}
    except ScopeVersionError:
        return {"base": "unsupported_version"}
    except Exception:  # noqa: BLE001 -- show the form again, log the surprise
        LOGGER.exception("Unexpected error talking to the scope box")
        return {"base": "unknown"}
    return {}


class ScopeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Host, port and token, typed once and checked against the box."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]})
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"XY Scope ({user_input[CONF_HOST]})",
                    data=user_input,
                    # Start feeding straight away from the best guesses; the
                    # options form shows them and every one can be changed.
                    options=suggest_options(self.hass),
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _box_schema({}), user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_box_schema(entry.data),
            errors=errors)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
            errors = await _validate(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD))}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> ScopeOptionsFlow:
        return ScopeOptionsFlow()


class ScopeOptionsFlow(OptionsFlow):
    """One entity per screen input, plus the display's outlet. Every field is
    optional; a cleared one stops that input (the screen shows `--`)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema({vol.Optional(k): sel for k, sel in _SELECTORS.items()})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, self.config_entry.options),
        )
