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
)
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv

from custom_components.pik_intercom.const import (
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
    CONF_IOT_UPDATE_INTERVAL,
    DEFAULT_METERS_UPDATE_INTERVAL,
    MIN_IOT_UPDATE_INTERVAL,
    CONF_ICM_SEPARATE_UPDATES,
    DEFAULT_ICM_SEPARATE_UPDATES,
    CONF_ADD_SUGGESTED_AREAS,
    DEFAULT_ADD_SUGGESTED_AREAS,
    DEFAULT_VERIFY_SSL,
)
from custom_components.pik_intercom.helpers import (
    phone_validator,
    async_get_authenticated_api,
)

_LOGGER: Final = logging.getLogger(__name__)

_INTERVALS_WITH_DEFAULTS: Final = {
    CONF_INTERCOMS_UPDATE_INTERVAL: (
        DEFAULT_INTERCOMS_UPDATE_INTERVAL,
        MIN_INTERCOMS_UPDATE_INTERVAL,
    ),
    CONF_AUTH_UPDATE_INTERVAL: (
        DEFAULT_AUTH_UPDATE_INTERVAL,
        MIN_AUTH_UPDATE_INTERVAL,
    ),
    CONF_LAST_CALL_SESSION_UPDATE_INTERVAL: (
        DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL,
        MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
    ),
    CONF_IOT_UPDATE_INTERVAL: (
        DEFAULT_METERS_UPDATE_INTERVAL,
        MIN_IOT_UPDATE_INTERVAL,
    ),
}

SHOW_INIT_OPTIONS = {
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(
        CONF_ADD_SUGGESTED_AREAS, default=DEFAULT_ADD_SUGGESTED_AREAS
    ): cv.boolean,
    vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
}

STEP_REAUTH_DATA_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
    }
)

STEP_USER_DATA_SCHEMA: Final = STEP_REAUTH_DATA_SCHEMA.extend(
    SHOW_INIT_OPTIONS
)


class PikIntercomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inter RAO config entries."""

    VERSION: Final = 8

    def __init__(self) -> None:
        """Init the config flow."""
        self._reauth_entry: ConfigEntry | None = None

    async def async_submit_entry(
        self, user_input: Mapping[str, Any]
    ) -> FlowResult:
        # Initialize API to get account identifier
        api = await async_get_authenticated_api(self.hass, user_input)

        unique_id = str(api.account.id)
        if not (entry := self._reauth_entry) or entry.unique_id != unique_id:
            # Check if entry with given username already exists
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        if entry:
            self.hass.config_entries.async_update_entry(
                entry,
                title=user_input[CONF_USERNAME],
                unique_id=unique_id,
                data={
                    **entry.data,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
                options={
                    **entry.options,
                    CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                },
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        # Create configuration entry
        username = user_input[CONF_USERNAME]
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
                **{
                    key: value
                    for key, (value, _) in _INTERVALS_WITH_DEFAULTS.items()
                },
            },
        )

    # Initial step for user interaction
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow start."""
        errors = {}
        description_placeholders = {}

        if user_input:
            username = None
            source_username = user_input[CONF_USERNAME]

            if "@" in source_username:
                try:
                    username = vol.Email(source_username)
                except vol.Invalid:
                    errors[CONF_USERNAME] = "bad_email_format"
            else:
                try:
                    username = phone_validator(source_username)
                except vol.Invalid:
                    errors[CONF_USERNAME] = "bad_phone_format"

            if not errors and username:
                user_input[CONF_USERNAME] = username
                try:
                    return await self.async_submit_entry(user_input)
                except ConfigEntryAuthFailed as exc:
                    user_input[CONF_USERNAME] = source_username
                    errors["base"] = "authentication_error"
                    description_placeholders["error"] = str(exc)

        if entry := self._reauth_entry:
            all_data = {**entry.data, **entry.options}

            # just in case it's broken, pop
            all_data.pop(CONF_PASSWORD, None)

            schema = self.add_suggested_values_to_schema(
                STEP_REAUTH_DATA_SCHEMA, all_data
            )
        else:
            schema = self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Import configuration entries from YAML"""
        return (
            (await self.async_submit_entry(user_input))
            if user_input
            else self.async_abort(reason="unknown_error")
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PikIntercomOptionsFlow(config_entry)


STEP_INIT_DATA_SCHEMA = vol.Schema(
    {
        **{
            vol.Required(key): cv.positive_time_period_dict
            for key in _INTERVALS_WITH_DEFAULTS
        },
        **SHOW_INIT_OPTIONS,
        vol.Optional(
            CONF_ICM_SEPARATE_UPDATES, default=DEFAULT_ICM_SEPARATE_UPDATES
        ): cv.boolean,
    }
)


class PikIntercomOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        options = self._config_entry.options
        errors = {}
        description_placeholders = {}
        normalized_configuration = {}

        if user_input:
            for key in _INTERVALS_WITH_DEFAULTS:
                normalized_configuration[key] = user_input[key].total_seconds()

            normalized_configuration[CONF_ICM_SEPARATE_UPDATES] = user_input[
                CONF_ICM_SEPARATE_UPDATES
            ]
            normalized_configuration[CONF_VERIFY_SSL] = user_input[
                CONF_VERIFY_SSL
            ]
            normalized_configuration[CONF_ADD_SUGGESTED_AREAS] = user_input[
                CONF_ADD_SUGGESTED_AREAS
            ]

            device_id = user_input[CONF_DEVICE_ID]
            if not re.fullmatch(r"[a-zA-Z0-9]+", device_id):
                errors[CONF_DEVICE_ID] = "device_id_invalid_characters"
            elif len(device_id) < MIN_DEVICE_ID_LENGTH:
                errors[CONF_DEVICE_ID] = "device_id_too_short"
            normalized_configuration[CONF_DEVICE_ID] = device_id

            for interval_key, (
                _,
                min_interval,
            ) in _INTERVALS_WITH_DEFAULTS.items():
                if (
                    normalized_configuration[interval_key] < min_interval
                    and normalized_configuration[interval_key] != 0
                ):
                    errors[interval_key] = interval_key + "_too_low"
                    description_placeholders["min_" + interval_key] = str(
                        timedelta(seconds=min_interval)
                    )

            if not errors:
                _LOGGER.debug(f"Saving options: {normalized_configuration}")
                return self.async_create_entry(
                    title="", data=normalized_configuration
                )
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
            data_schema=self.add_suggested_values_to_schema(
                STEP_INIT_DATA_SCHEMA, normalized_configuration
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
