__all__ = (
    "CONFIG_SCHEMA",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
    "DOMAIN",
)

import asyncio
import logging
from datetime import timedelta
from typing import Final, List

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikIntercomException,
)
from custom_components.pik_intercom.const import (
    CONF_AUTH_UPDATE_INTERVAL,
    CONF_INTERCOMS_UPDATE_INTERVAL,
    DATA_REAUTHENTICATORS,
    DEFAULT_AUTH_UPDATE_INTERVAL,
    DEFAULT_INTERCOMS_UPDATE_INTERVAL,
    DOMAIN,
    MIN_AUTH_UPDATE_INTERVAL,
    MIN_DEVICE_ID_LENGTH,
    MIN_INTERCOMS_UPDATE_INTERVAL,
    CONF_LAST_CALL_SESSION_UPDATE_INTERVAL,
    DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL,
    CONF_IOT_UPDATE_INTERVAL,
    DEFAULT_METERS_UPDATE_INTERVAL,
    MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
    MIN_IOT_UPDATE_INTERVAL,
    DATA_ENTITIES,
)
from custom_components.pik_intercom.entity import (
    BasePikIntercomUpdateCoordinator,
    PikIntercomPropertyIntercomsUpdateCoordinator,
    PikIntercomIotIntercomsUpdateCoordinator,
    PikIntercomIotCamerasUpdateCoordinator,
    PikIntercomIotMetersUpdateCoordinator,
    PikIntercomLastCallSessionUpdateCoordinator,
)
from custom_components.pik_intercom.helpers import (
    phone_validator,
    patch_haffmpeg,
    mask_username,
)

_LOGGER: Final = logging.getLogger(__name__)

PLATFORMS: Final = (
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
)

_BASE_CONFIG_ENTRY_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_USERNAME): vol.All(
            cv.string, vol.Any(phone_validator, vol.Email)
        ),
        vol.Required(CONF_PASSWORD): cv.string,
        # Additional parameters
        vol.Optional(CONF_DEVICE_ID, default=None): vol.Any(
            vol.Equal(None),
            vol.All(cv.string, vol.Length(min=MIN_DEVICE_ID_LENGTH)),
        ),
    }
)

CONFIG_ENTRY_SCHEMA: Final = vol.All(
    # Forcefully deprecate client app configuration
    cv.removed("client_app", raise_if_present=False),
    cv.removed("client_os", raise_if_present=False),
    cv.removed("client_version", raise_if_present=False),
    cv.removed("user_agent", raise_if_present=False),
    cv.removed("call_sessions_update_interval", raise_if_present=False),
    cv.removed(CONF_AUTH_UPDATE_INTERVAL, raise_if_present=False),
    cv.removed(CONF_INTERCOMS_UPDATE_INTERVAL, raise_if_present=False),
    # Validate base schema
    _BASE_CONFIG_ENTRY_SCHEMA,
)

CONFIG_SCHEMA: Final = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            cv.remove_falsy,
            [CONFIG_ENTRY_SCHEMA],
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the PIK Intercom component."""
    # Patch HAffmpeg
    # @TODO: check if still required
    patch_haffmpeg()

    # Check if YAML configuration is present
    if not (domain_config := config.get(DOMAIN)):
        return True

    # Import existing configurations
    configured_users = {
        entry.data.get(CONF_USERNAME)
        for entry in hass.config_entries.async_entries(DOMAIN)
    }
    for user_cfg in domain_config:
        if user_cfg.get(CONF_USERNAME) in configured_users:
            continue
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=user_cfg,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    user_cfg = entry.data
    config_entry_id = entry.entry_id
    log_prefix = f"[{mask_username(user_cfg[CONF_USERNAME])}] "

    api_object = PikIntercomAPI(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
        device_id=entry.options[CONF_DEVICE_ID],
    )

    try:
        await api_object.async_authenticate()
        await api_object.async_update_customer_device()
    except PikIntercomException as exc:
        msg = f"Невозможно выполнить авторизацию: {exc}"
        _LOGGER.error(log_prefix + msg, exc_info=exc)
        raise ConfigEntryAuthFailed(msg) from exc

    try:
        await api_object.async_update_properties()
    except PikIntercomException as exc:
        msg = f"Невозможно выполнить обновление данных: {exc}"
        _LOGGER.error(log_prefix + msg, exc_info=exc)
        raise ConfigEntryNotReady(msg) from exc

    # Load property device coordinators
    if (update_interval := entry.options[CONF_INTERCOMS_UPDATE_INTERVAL]) > 0:
        update_interval = timedelta(
            seconds=max(MIN_INTERCOMS_UPDATE_INTERVAL, update_interval)
        )
        _LOGGER.debug(
            log_prefix
            + f"Setting up property intercoms updates with interval: {update_interval}"
        )
    else:
        update_interval = None
        _LOGGER.debug(
            log_prefix + f"Not setting up property intercoms updates"
        )
    entry_update_coordinators: List["BasePikIntercomUpdateCoordinator"] = [
        PikIntercomPropertyIntercomsUpdateCoordinator(
            hass,
            api_object=api_object,
            property_id=property_.id,
            update_interval=update_interval,
        )
        for property_ in api_object.properties.values()
    ]

    # Load IoT device coordinators
    if (update_interval := entry.options[CONF_IOT_UPDATE_INTERVAL]) > 0:
        update_interval = timedelta(
            seconds=max(MIN_IOT_UPDATE_INTERVAL, update_interval)
        )
        _LOGGER.debug(
            log_prefix
            + f"Setting up IoT devices updates with interval: {update_interval}"
        )
    else:
        update_interval = None
        _LOGGER.debug(log_prefix + f"Not setting up IoT devices updates")
    for coordinator_cls in (
        PikIntercomIotCamerasUpdateCoordinator,
        PikIntercomIotMetersUpdateCoordinator,
        PikIntercomIotIntercomsUpdateCoordinator,
    ):
        entry_update_coordinators.append(
            coordinator_cls(
                hass,
                api_object=api_object,
                update_interval=update_interval,
            )
        )

    # Load call session update coordinator
    if (
        update_interval := entry.options[
            CONF_LAST_CALL_SESSION_UPDATE_INTERVAL
        ]
    ) > 0:
        update_interval = timedelta(
            seconds=max(
                MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
                update_interval,
            )
        )
        _LOGGER.debug(
            log_prefix
            + f"Setting up last call session updates with interval: {update_interval}"
        )
    else:
        update_interval = None
        _LOGGER.debug(log_prefix + f"Not setting up last call session updates")
    entry_update_coordinators.append(
        PikIntercomLastCallSessionUpdateCoordinator(
            hass, api_object=api_object, update_interval=update_interval
        )
    )

    # Perform initial update tasks
    done, pending = await asyncio.wait(
        [
            hass.loop.create_task(
                coordinator.async_config_entry_first_refresh()
            )
            for coordinator in entry_update_coordinators
        ],
        return_when=asyncio.FIRST_EXCEPTION,
    )

    # Cancel remaining update tasks, if any
    for task in pending:
        task.cancel()

    # If first task finished with an exception, raise it
    if exc := next(iter(done)).exception():
        raise ConfigEntryNotReady(f"One of the updates failed: {exc}") from exc

    # Helper: cleanup unused properties
    required_properties = {
        device.property_id for device in api_object.devices.values()
    }
    shutdown_tasks = []
    for coordinator in tuple(entry_update_coordinators):
        if (
            isinstance(
                coordinator, PikIntercomPropertyIntercomsUpdateCoordinator
            )
            and coordinator.property_id not in required_properties
        ):
            entry_update_coordinators.remove(coordinator)
            hass.loop.create_task(coordinator.async_shutdown())
            _LOGGER.debug(
                log_prefix + f"Property {coordinator.property_id} "
                f"update coordinator is not needed, shutting down"
            )
    if shutdown_tasks:
        await asyncio.wait(shutdown_tasks, return_when=asyncio.ALL_COMPLETED)

    # Save update coordinators
    hass.data.setdefault(DOMAIN, {})[
        entry.entry_id
    ] = entry_update_coordinators
    hass.data.setdefault(DATA_ENTITIES, {})[entry.entry_id] = {}

    # Create automatic authentication updater
    async def async_reauthenticate(*_):
        _LOGGER.debug(log_prefix + "Выполнение профилактической реавторизации")

        await api_object.async_authenticate()

    if (update_interval := entry.options[CONF_AUTH_UPDATE_INTERVAL]) > 0:
        update_interval = timedelta(
            seconds=max(MIN_AUTH_UPDATE_INTERVAL, update_interval)
        )
        _LOGGER.debug(
            log_prefix
            + f"Setting up reauthentication with interval: {update_interval}"
        )
        hass.data.setdefault(DATA_REAUTHENTICATORS, {})[
            config_entry_id
        ] = async_track_time_interval(
            hass,
            async_reauthenticate,
            update_interval,
        )
    else:
        _LOGGER.debug(log_prefix + "Will not setup reauthentication")

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when its updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Pik Intercom entry"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from custom_components.pik_intercom.config_flow import (
        PikIntercomConfigFlow,
    )

    _LOGGER.info(
        f"[{entry.entry_id}] Upgrading configuration version: {entry.version} => {PikIntercomConfigFlow.VERSION}"
    )

    data = dict(entry.data)
    options = dict(entry.options)

    # Add default options
    options.setdefault(CONF_DEVICE_ID, entry.entry_id[-16:])
    options.setdefault(
        CONF_INTERCOMS_UPDATE_INTERVAL, DEFAULT_INTERCOMS_UPDATE_INTERVAL
    )
    options.setdefault(
        CONF_LAST_CALL_SESSION_UPDATE_INTERVAL,
        DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL,
    )
    options.setdefault(CONF_AUTH_UPDATE_INTERVAL, DEFAULT_AUTH_UPDATE_INTERVAL)
    options.setdefault(
        CONF_IOT_UPDATE_INTERVAL, DEFAULT_METERS_UPDATE_INTERVAL
    )
    options.setdefault(CONF_VERIFY_SSL, True)

    # Remove obsolete data
    options.pop("call_sessions_update_interval", None)

    entry.version = PikIntercomConfigFlow.VERSION
    hass.config_entries.async_update_entry(entry, data=data, options=options)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        # Clear authentication updater
        if auth_updater := hass.data.get(DATA_REAUTHENTICATORS, {}).pop(
            entry.entry_id, None
        ):
            auth_updater()

    hass.data.get(DOMAIN, {}).pop(entry.entry_id)
    hass.data.get(DATA_ENTITIES, {}).pop(entry.entry_id)

    return unload_ok
