"""Pik Intercom integration config and option flow handlers"""
__all__ = (
    "PikIntercomConfigFlow",
    "PikIntercomOptionsFlow",
)

import logging
import re
from binascii import b2a_hex
from datetime import timedelta
from os import urandom
from typing import Any, Dict, Final, Optional, Mapping

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
    CONN_CLASS_CLOUD_POLL,
)
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PikIntercomAPI, PikIntercomException
from .const import (
    CONF_AUTH_UPDATE_INTERVAL,
    CONF_INTERCOMS_UPDATE_INTERVAL,
    CONF_LAST_CALL_SESSION_UPDATE_INTERVAL,
    DEFAULT_AUTH_UPDATE_INTERVAL,
    DEFAULT_INTERCOMS_UPDATE_INTERVAL,
    DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL,
    DOMAIN,
    MIN_AUTH_UPDATE_INTERVAL,
    MIN_DEVICE_ID_LENGTH,
    MIN_INTERCOMS_UPDATE_INTERVAL,
    MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
)
from .helpers import phone_validator

_LOGGER: Final = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)

_INTERVALS_WITH_DEFAULTS = {
    CONF_INTERCOMS_UPDATE_INTERVAL: (DEFAULT_INTERCOMS_UPDATE_INTERVAL, MIN_INTERCOMS_UPDATE_INTERVAL),
    CONF_AUTH_UPDATE_INTERVAL: (DEFAULT_AUTH_UPDATE_INTERVAL, MIN_AUTH_UPDATE_INTERVAL),
    CONF_LAST_CALL_SESSION_UPDATE_INTERVAL: (
        DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL,
        MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
    ),
}


class PikIntercomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inter RAO config entries."""

    VERSION = 5
    CONNECTION_CLASS = CONN_CLASS_CLOUD_POLL

    async def async_submit_entry(self, user_input: Mapping[str, Any]) -> FlowResult:
        username = user_input[CONF_USERNAME]

        # Check if entry with given username already exists
        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured()

        # Create configuration entry
        return self.async_create_entry(
            title=(
                username
                if "@" in username
                else f"+{username[1]} ({username[2:5]}) {username[5:8]}-{username[8:10]}-{username[10:]}"
            ),
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            },
            options={
                CONF_DEVICE_ID: user_input[CONF_DEVICE_ID],
                CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                **{key: value for key, (value, _) in _INTERVALS_WITH_DEFAULTS.items()},
            },
        )

    # Initial step for user interaction
    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle a flow start."""
        if not user_input:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_USER_DATA_SCHEMA,
                    suggested_values={CONF_DEVICE_ID: b2a_hex(urandom(15)).decode("ascii")},
                ),
            )

        errors = {}
        description_placeholders = {}

        username = user_input[CONF_USERNAME]

        if "@" in username:
            try:
                username = vol.Email(username)
            except vol.Invalid:
                errors[CONF_USERNAME] = "bad_email_format"
        else:
            try:
                username = phone_validator(username)
            except vol.Invalid:
                errors[CONF_USERNAME] = "bad_phone_format"

        if not errors:
            api = PikIntercomAPI(
                username=username,
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
                device_id=user_input[CONF_DEVICE_ID],
            )

            try:
                await api.async_authenticate()
            except PikIntercomException as exc:
                _LOGGER.error(f"Authentication error: {exc}")
                errors["base"] = "authentication_error"
                description_placeholders["error"] = str(exc)
            else:
                user_input[CONF_USERNAME] = username
                return await self.async_submit_entry(user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, suggested_values=user_input),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_import(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Import configuration entries from YAML"""
        return (await self.async_submit_entry(user_input)) if user_input else self.async_abort(reason="unknown_error")

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        # @TODO
        raise NotImplementedError

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PikIntercomOptionsFlow(config_entry)


STEP_INIT_DATA_SCHEMA = vol.Schema(
    {
        **{vol.Required(key): cv.positive_time_period_dict for key in _INTERVALS_WITH_DEFAULTS},
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
    }
)


class PikIntercomOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        options = self._config_entry.options
        errors = {}
        description_placeholders = {}
        normalized_configuration = {}

        if user_input:
            for key in _INTERVALS_WITH_DEFAULTS:
                normalized_configuration[key] = user_input[key].total_seconds()

            normalized_configuration[CONF_VERIFY_SSL] = user_input[CONF_VERIFY_SSL]

            device_id = user_input[CONF_DEVICE_ID]
            if not re.fullmatch(r"[a-zA-Z0-9]+", device_id):
                errors[CONF_DEVICE_ID] = "device_id_invalid_characters"
            elif len(device_id) < MIN_DEVICE_ID_LENGTH:
                errors[CONF_DEVICE_ID] = "device_id_too_short"
            normalized_configuration[CONF_DEVICE_ID] = device_id

            for interval_key, (_, min_interval) in _INTERVALS_WITH_DEFAULTS.items():
                if normalized_configuration[interval_key] < min_interval:
                    errors[interval_key] = interval_key + "_too_low"
                    description_placeholders["min_" + interval_key] = str(timedelta(seconds=min_interval))

            if not errors:
                _LOGGER.debug(f"Saving options: {normalized_configuration}")
                return self.async_create_entry(title="", data=normalized_configuration)
        else:
            normalized_configuration = dict(options)

        for interval_key in _INTERVALS_WITH_DEFAULTS:
            current_value = normalized_configuration[interval_key]
            normalized_configuration[interval_key] = {
                "hours": current_value // 3600,
                "minutes": (current_value % 3600) // 60,
                "seconds": current_value % 60,
            }

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(STEP_INIT_DATA_SCHEMA, normalized_configuration),
            errors=errors,
            description_placeholders=description_placeholders,
        )
