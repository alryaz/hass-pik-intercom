"""Inter RAO integration config and option flow handlers"""
import logging
from collections import OrderedDict
from typing import Any, ClassVar, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.typing import ConfigType

from custom_components.pik_intercom import _phone_validator
from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.api import PikIntercomAPI, PikIntercomException

_LOGGER = logging.getLogger(__name__)

__all__ = ("PikIntercomConfigFlow",)


class PikIntercomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inter RAO config entries."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    CACHED_API_TYPE_NAMES: ClassVar[Optional[Dict[str, Any]]] = {}

    def __init__(self):
        """Instantiate config flow."""
        self.schema_user: Optional[vol.Schema] = None

    async def _check_entry_exists(self, username: str):
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
        self, user_input: Optional[ConfigType] = None
    ) -> Dict[str, Any]:
        """Handle a flow start."""
        if self.schema_user is None:
            schema_user = OrderedDict()
            schema_user[vol.Required(CONF_USERNAME)] = str
            schema_user[vol.Required(CONF_PASSWORD)] = str
            self.schema_user = vol.Schema(schema_user)

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self.schema_user)

        username = user_input[CONF_USERNAME]

        if "@" in username:
            try:
                username = vol.Email(username)
            except vol.Invalid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.schema_user,
                    errors={CONF_USERNAME: "bad_email_format"},
                )
        else:
            try:
                username = _phone_validator(username)
            except vol.Invalid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.schema_user,
                    errors={CONF_USERNAME: "bad_phone_format"},
                )

        if await self._check_entry_exists(username):
            return self.async_abort(reason="already_configured_service")

        async with PikIntercomAPI(
            username=username,
            password=user_input[CONF_PASSWORD],
        ) as api:
            try:
                await api.async_authenticate()

            except PikIntercomException as e:
                _LOGGER.error(f"Authentication error: {repr(e)}")
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.schema_user,
                    errors={"base": "authentication_error"},
                )

            try:
                await api.async_update_properties()

            except PikIntercomException as e:
                _LOGGER.error(f"Request error: {repr(e)}")
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.schema_user,
                    errors={"base": "update_accounts_error"},
                )

            else:
                if not api.apartments:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self.schema_user,
                        errors={"base": "empty_account"},
                    )

        return self.async_create_entry(
            title=self._make_entry_title(username),
            data=user_input,
        )

    async def async_step_import(
        self, user_input: Optional[ConfigType] = None
    ) -> Dict[str, Any]:
        _LOGGER.debug("Executing import step: %s", user_input)

        if user_input is None:
            return self.async_abort(reason="unknown_error")

        username = user_input[CONF_USERNAME]

        if await self._check_entry_exists(username):
            return self.async_abort(reason="already_exists")

        return self.async_create_entry(
            title=self._make_entry_title(username),
            data={CONF_USERNAME: username},
        )
