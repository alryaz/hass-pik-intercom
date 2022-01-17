"""Pik Intercom integration config and option flow handlers"""
__all__ = (
    "PikIntercomConfigFlow",
    "PikIntercomOptionsFlow",
    "DEFAULT_OPTIONS",
)

import logging
import re
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Dict, Final, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
    SOURCE_IMPORT,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from custom_components.pik_intercom._base import phone_validator
from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikIntercomException,
)
from custom_components.pik_intercom.const import (
    CONF_AUTH_UPDATE_INTERVAL,
    CONF_CALL_SESSIONS_UPDATE_INTERVAL,
    CONF_INTERCOMS_UPDATE_INTERVAL,
    DEFAULT_AUTH_UPDATE_INTERVAL,
    DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL,
    DEFAULT_INTERCOMS_UPDATE_INTERVAL,
    DOMAIN,
    MIN_AUTH_UPDATE_INTERVAL,
    MIN_CALL_SESSIONS_UPDATE_INTERVAL,
    MIN_DEVICE_ID_LENGTH,
    MIN_INTERCOMS_UPDATE_INTERVAL,
)

_LOGGER: Final = logging.getLogger(__name__)

DEFAULT_OPTIONS: Final = MappingProxyType(
    {
        CONF_INTERCOMS_UPDATE_INTERVAL: DEFAULT_INTERCOMS_UPDATE_INTERVAL,
        CONF_CALL_SESSIONS_UPDATE_INTERVAL: DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL,
        CONF_AUTH_UPDATE_INTERVAL: DEFAULT_AUTH_UPDATE_INTERVAL,
    }
)


class PikIntercomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inter RAO config entries."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def _check_entry_exists(self, username: str):
        current_entries = self._async_current_entries()

        for config_entry in current_entries:
            if config_entry.data[CONF_USERNAME] == username:
                return True

        return False

    @staticmethod
    def _make_entry_title(username: str) -> str:
        if "@" in username:
            return username
        return f"+{username[1]} ({username[2:5]}) {username[5:8]}-{username[8:10]}-{username[10:]}"

    # Initial step for user interaction
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle a flow start."""
        errors = {}
        description_placeholders = {}

        if user_input:
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
                if self._check_entry_exists(username):
                    return self.async_abort(
                        reason="already_configured_service"
                    )

                async with PikIntercomAPI(
                    username=username,
                    password=user_input[CONF_PASSWORD],
                    device_id=user_input[CONF_DEVICE_ID],
                ) as api:
                    user_input[CONF_DEVICE_ID] = api.device_id

                    try:
                        await api.async_authenticate()
                    except PikIntercomException as e:
                        _LOGGER.error(f"Authentication error: {repr(e)}")
                        errors["base"] = "authentication_error"
                        description_placeholders["error"] = str(e)
                    else:
                        try:
                            await api.async_update_properties()

                        except PikIntercomException as e:
                            _LOGGER.error(f"Request error: {repr(e)}")
                            errors["base"] = "update_accounts_error"
                            description_placeholders["error"] = str(e)
                        else:
                            if api.properties:
                                options = dict(DEFAULT_OPTIONS)
                                options[CONF_DEVICE_ID] = api.device_id
                                return self.async_create_entry(
                                    title=self._make_entry_title(username),
                                    data={
                                        CONF_USERNAME: username,
                                        CONF_PASSWORD: user_input[
                                            CONF_PASSWORD
                                        ],
                                    },
                                    options=options,
                                )
                            errors["base"] = "empty_account"
        else:
            user_input = {}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=user_input.get(CONF_USERNAME, ""),
                    ): cv.string,
                    vol.Required(
                        CONF_PASSWORD,
                        default=user_input.get(CONF_PASSWORD, ""),
                    ): cv.string,
                    vol.Optional(
                        CONF_DEVICE_ID,
                        default=user_input.get(CONF_DEVICE_ID, ""),
                    ): cv.string,
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        _LOGGER.debug("Executing import step: %s", user_input)

        if user_input is None:
            return self.async_abort(reason="unknown_error")

        username = user_input[CONF_USERNAME]

        if self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        return self.async_create_entry(
            title=self._make_entry_title(username),
            data={CONF_USERNAME: username},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PikIntercomOptionsFlow(config_entry)


class PikIntercomOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if self._config_entry.source == SOURCE_IMPORT:
            return self.async_abort(reason="yaml_config_unsupported")

        options = self._config_entry.options
        errors = {}
        description_placeholders = {}

        interval_values = {
            key: (
                user_input[key].total_seconds() if user_input else options[key]
            )
            for key in (
                CONF_INTERCOMS_UPDATE_INTERVAL,
                CONF_CALL_SESSIONS_UPDATE_INTERVAL,
                CONF_AUTH_UPDATE_INTERVAL,
            )
        }

        if user_input:
            device_id = user_input[CONF_DEVICE_ID]
            if not re.fullmatch(r"[a-zA-Z0-9]+", device_id):
                errors[CONF_DEVICE_ID] = "device_id_invalid_characters"
            elif len(device_id) < MIN_DEVICE_ID_LENGTH:
                errors[CONF_DEVICE_ID] = "device_id_too_short"

            for interval_key, min_interval in (
                (
                    CONF_INTERCOMS_UPDATE_INTERVAL,
                    MIN_INTERCOMS_UPDATE_INTERVAL,
                ),
                (
                    CONF_CALL_SESSIONS_UPDATE_INTERVAL,
                    MIN_CALL_SESSIONS_UPDATE_INTERVAL,
                ),
                (CONF_AUTH_UPDATE_INTERVAL, MIN_AUTH_UPDATE_INTERVAL),
            ):
                if interval_values[interval_key] < min_interval:
                    errors[interval_key] = interval_key + "_too_low"
                    description_placeholders["min_" + interval_key] = str(
                        timedelta(seconds=min_interval)
                    )

            if not errors:
                interval_values[CONF_DEVICE_ID] = device_id
                return self.async_create_entry(title="", data=interval_values)
        else:
            device_id = options[CONF_DEVICE_ID]

        schema_dict = {
            vol.Required(
                interval_key,
                default={
                    "hours": current_value // 3600,
                    "minutes": (current_value % 3600) // 60,
                    "seconds": current_value % 60,
                },
            ): cv.positive_time_period_dict
            for interval_key, current_value in interval_values.items()
        }
        schema_dict[
            vol.Required(CONF_DEVICE_ID, default=device_id)
        ] = cv.string

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders=description_placeholders,
        )
