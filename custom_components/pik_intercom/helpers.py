import logging
import re
from typing import (
    MutableMapping,
    Any,
    final,
    Union,
    Mapping,
    Final,
)

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_VERIFY_SSL,
    CONF_DEVICE_ID,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.pik_intercom.const import DEFAULT_VERIFY_SSL, DOMAIN
from pik_intercom import PikIntercomAPI, PikIntercomException

_LOGGER: Final = logging.getLogger(__name__)

_RE_USERNAME_MASK: Final = re.compile(r"^(\W*)(.).*(.)$")


class ConfigEntryLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that prefixes config entry ID."""

    def __init__(
        self,
        logger: logging.Logger = _LOGGER,
        entry: ConfigEntry | str | None = None,
    ) -> None:
        super().__init__(logger, {})
        if entry is None:
            entry = config_entries.current_entry.get()
            if entry is None:
                entry = "?" * 6
        self.config_entry_id = entry

    @property
    @final
    def config_entry_id(self) -> str:
        return self._config_entry_id

    @config_entry_id.setter
    @final
    def config_entry_id(self, value: ConfigEntry | str) -> None:
        self._config_entry_id = (
            value.entry_id if isinstance(value, ConfigEntry) else str(value)
        )
        self._shortened_entry_id = self._config_entry_id[-6:]

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        return "[%s] %s" % (self._shortened_entry_id, msg), kwargs


AnyLogger = Union[logging.Logger, ConfigEntryLoggerAdapter]


def get_logger(logger: AnyLogger) -> ConfigEntryLoggerAdapter:
    if isinstance(logger, ConfigEntryLoggerAdapter):
        return logger
    return ConfigEntryLoggerAdapter(logger)


def phone_validator(phone_number: str) -> str:
    """Validate and convert phone number into bare format."""

    phone_number = re.sub(r"\D", "", phone_number)

    if len(phone_number) == 10:
        return "+7" + phone_number

    elif len(phone_number) == 11:
        if phone_number.startswith("8"):
            return "+7" + phone_number[1:]
        elif phone_number.startswith("7"):
            return "+" + phone_number
        else:
            raise vol.Invalid("Unknown phone number format detected")
    else:
        raise vol.Invalid(
            f"Irregular phone number length (expected 11, got {len(phone_number)})"
        )


def patch_haffmpeg():
    """Patch HA ffmpeg adapter to put rtsp_transport before input stream when
    a certain non-existent command line argument (input_rtsp_transport) is provided.

    """

    try:
        from haffmpeg.core import HAFFmpeg
    except (ImportError, FileNotFoundError):
        _LOGGER.warning(
            "haffmpeg could not be patched because it is not yet installed"
        )
        return

    if hasattr(HAFFmpeg, "_orig_generate_ffmpeg_cmd"):
        return

    # noinspection PyProtectedMember
    HAFFmpeg._orig_generate_ffmpeg_cmd = HAFFmpeg._generate_ffmpeg_cmd

    def _generate_ffmpeg_cmd(self, *args, **kwargs) -> None:
        """Generate ffmpeg command line (patched to support input_rtsp_transport argument)."""
        self._orig_generate_ffmpeg_cmd(*args, **kwargs)

        _argv = self._argv
        try:
            rtsp_flags_index = _argv.index("-prefix_rtsp_flags")
        except ValueError:
            return
        try:
            rtsp_transport_spec = _argv[rtsp_flags_index + 1]
        except IndexError:
            return
        else:
            if not rtsp_transport_spec.startswith("-"):
                del _argv[rtsp_flags_index : rtsp_flags_index + 2]
                _argv.insert(1, "-rtsp_flags")
                _argv.insert(2, rtsp_transport_spec)

    HAFFmpeg._generate_ffmpeg_cmd = _generate_ffmpeg_cmd


async def async_get_authenticated_api(
    hass: HomeAssistant,
    entry: Union[ConfigEntry, Mapping[str, Any]],
    *,
    logger: AnyLogger = _LOGGER,
) -> PikIntercomAPI:
    """
    Retrieve authenticated API object from config entry / dict data.
    :param hass: Home Assistant object
    :param entry: Config entry / dict data
    :param logger: Logger to use
    :return: Authenticated API object
    """
    logger = get_logger(logger)

    api_object = (
        PikIntercomAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            session=async_get_clientsession(
                hass,
                verify_ssl=entry.options.get(
                    CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                ),
            ),
            device_id=entry.options.get(CONF_DEVICE_ID) or entry.entry_id,
        )
        if isinstance(entry, ConfigEntry)
        else PikIntercomAPI(
            username=entry[CONF_USERNAME],
            password=entry[CONF_PASSWORD],
            session=async_get_clientsession(
                hass, verify_ssl=entry.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ),
            device_id=entry.get(CONF_DEVICE_ID),
        )
    )

    try:
        await api_object.authenticate()
    except aiohttp.ClientResponseError as exc:
        if not (400 <= exc.status < 500):
            raise
        logger.error(f"Authentication error: {exc}", exc_info=exc)
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except PikIntercomException as exc:
        logger.error(f"Authentication error: {exc}", exc_info=exc)
        raise ConfigEntryAuthFailed(str(exc)) from exc

    return api_object


def async_change_device_prefix(
    hass: HomeAssistant,
    entry: ConfigEntry,
    from_prefix: str,
    to_prefix: str,
    *,
    logger: AnyLogger = _LOGGER,
) -> None:
    """Update unique ID prefix (which, unfortunately, happens regularly during development)."""
    logger = get_logger(logger)

    from homeassistant.helpers.entity_registry import (
        async_get,
        async_entries_for_config_entry,
    )

    ent_reg = async_get(hass)
    for ent in async_entries_for_config_entry(ent_reg, entry.entry_id):
        if not ent.unique_id.startswith(from_prefix):
            continue
        new_unique_id = to_prefix + ent.unique_id[len(from_prefix) :]
        logger.debug(f"Updated unique ID: {ent.unique_id} => {new_unique_id}")
        ent_reg.async_update_entity(ent.entity_id, new_unique_id=new_unique_id)

    from homeassistant.helpers.device_registry import (
        async_get,
        async_entries_for_config_entry,
    )

    dev_reg = async_get(hass)
    for dev in async_entries_for_config_entry(dev_reg, entry.entry_id):
        new_identifiers = set()
        for first_part, second_part in dev.identifiers:
            if first_part == DOMAIN and second_part.startswith(from_prefix):
                new_second_part = to_prefix + second_part[len(from_prefix) :]
                logger.debug(
                    f"Updated dev ID: {second_part} => {new_second_part}"
                )
                second_part = new_second_part
            new_identifiers.add((first_part, second_part))
        if dev.identifiers == new_identifiers:
            continue
        dev_reg.async_update_device(
            dev.id,
            new_identifiers=new_identifiers,
        )
