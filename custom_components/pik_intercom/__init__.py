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
from typing import (
    Final,
    List,
)

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from custom_components.pik_intercom.api import (
    DEFAULT_CLIENT_APP,
    DEFAULT_CLIENT_OS,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_USER_AGENT,
    PikIntercomAPI,
    PikIntercomException,
)
from custom_components.pik_intercom.const import (
    CONF_AUTH_UPDATE_INTERVAL,
    CONF_CALL_SESSIONS_UPDATE_INTERVAL,
    CONF_INTERCOMS_UPDATE_INTERVAL,
    DATA_REAUTHENTICATORS,
    DEFAULT_AUTH_UPDATE_INTERVAL,
    DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL,
    DEFAULT_INTERCOMS_UPDATE_INTERVAL,
    DOMAIN,
    MIN_AUTH_UPDATE_INTERVAL,
    MIN_CALL_SESSIONS_UPDATE_INTERVAL,
    MIN_DEVICE_ID_LENGTH,
    MIN_INTERCOMS_UPDATE_INTERVAL,
)
from .helpers import (
    phone_validator,
    patch_haffmpeg,
    mask_username,
)
from .entity import (
    BasePikIntercomUpdateCoordinator,
    PikIntercomPropertyIntercomsUpdateCoordinator,
    PikIntercomIotIntercomsUpdateCoordinator,
    PikIntercomIotCamerasUpdateCoordinator,
    PikIntercomIotMetersUpdateCoordinator,
    PikIntercomLastCallSessionUpdateCoordinator,
)

_LOGGER: Final = logging.getLogger(__name__)

PLATFORMS = (
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
)

_BASE_CONFIG_ENTRY_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_USERNAME): vol.All(cv.string, vol.Any(phone_validator, vol.Email)),
        vol.Required(CONF_PASSWORD): cv.string,
        # Additional parameters
        vol.Optional(CONF_DEVICE_ID, default=None): vol.Any(
            vol.Equal(None),
            vol.All(cv.string, vol.Length(min=MIN_DEVICE_ID_LENGTH)),
        ),
        # Update intervals (DEPRECATED OPTIONS)
        vol.Optional(
            CONF_INTERCOMS_UPDATE_INTERVAL,
            default=timedelta(seconds=DEFAULT_INTERCOMS_UPDATE_INTERVAL),
            description="Intercoms update interval",
        ): vol.All(
            cv.positive_time_period,
            vol.Clamp(min=timedelta(seconds=MIN_CALL_SESSIONS_UPDATE_INTERVAL)),
        ),
        vol.Optional(
            CONF_CALL_SESSIONS_UPDATE_INTERVAL,
            default=timedelta(seconds=DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL),
            description="Call sessions update interval",
        ): vol.All(
            cv.positive_time_period,
            vol.Clamp(min=timedelta(seconds=MIN_CALL_SESSIONS_UPDATE_INTERVAL)),
        ),
        vol.Optional(
            CONF_AUTH_UPDATE_INTERVAL,
            default=timedelta(seconds=DEFAULT_AUTH_UPDATE_INTERVAL),
            description="Authentication update interval",
        ): vol.All(
            cv.positive_time_period,
            vol.Clamp(min=timedelta(seconds=MIN_AUTH_UPDATE_INTERVAL)),
        ),
    }
)

CONFIG_ENTRY_SCHEMA: Final = vol.All(
    # Forcefully deprecate client app configuration
    cv.removed("client_app", raise_if_present=False),
    cv.removed("client_os", raise_if_present=False),
    cv.removed("client_version", raise_if_present=False),
    cv.removed("user_agent", raise_if_present=False),
    # Deprecate interval configurations
    cv.deprecated(CONF_INTERCOMS_UPDATE_INTERVAL),
    cv.deprecated(CONF_AUTH_UPDATE_INTERVAL),
    cv.deprecated(CONF_CALL_SESSIONS_UPDATE_INTERVAL),
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


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Set up the PIK Intercom component."""
    # Patch HAffmpeg
    # @TODO: check if still required
    patch_haffmpeg()

    # Check if YAML configuration is present
    if not (domain_config := config.get(DOMAIN)):
        return True

    # Import existing configurations
    configured_users = {entry.data.get(CONF_USERNAME) for entry in hass.config_entries.async_entries(DOMAIN)}
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

    intercoms_update_interval = timedelta(
        seconds=max(
            MIN_INTERCOMS_UPDATE_INTERVAL,
            entry.options[CONF_INTERCOMS_UPDATE_INTERVAL],
        )
    )

    # Load property device coordinators
    entry_update_coordinators: List["BasePikIntercomUpdateCoordinator"] = [
        PikIntercomPropertyIntercomsUpdateCoordinator(
            hass,
            api_object=api_object,
            property_id=property_.id,
            update_interval=intercoms_update_interval,
        )
        for property_ in api_object.properties.values()
    ]

    # Load IoT device coordinators
    for coordinator_cls in (
        PikIntercomIotCamerasUpdateCoordinator,
        PikIntercomIotMetersUpdateCoordinator,
        PikIntercomIotIntercomsUpdateCoordinator,
    ):
        entry_update_coordinators.append(
            coordinator_cls(
                hass,
                api_object=api_object,
                update_interval=intercoms_update_interval,
            )
        )

    entry_update_coordinators.append(
        PikIntercomLastCallSessionUpdateCoordinator(
            hass,
            api_object=api_object,
            update_interval=timedelta(milliseconds=2500),
        )
    )

    # Perform initial update tasks
    done, pending = await asyncio.wait(
        [
            hass.loop.create_task(coordinator.async_config_entry_first_refresh())
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

    # Save update coordinators
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry_update_coordinators

    # Create automatic authentication updater
    async def async_reauthenticate(*_):
        _LOGGER.debug(log_prefix + "Выполнение профилактической реавторизации")

        await api_object.async_authenticate()

    hass.data.setdefault(DATA_REAUTHENTICATORS, {})[config_entry_id] = async_track_time_interval(
        hass,
        async_reauthenticate,
        timedelta(seconds=entry.options[CONF_AUTH_UPDATE_INTERVAL]),
    )

    # # @TODO: code above must be uncommented to work
    # if push_credentials:
    #     def async_handle_notification(obj, notification, data_message):
    #         _LOGGER.info(f"Received notification object: {obj}")
    #         _LOGGER.info(f"Received notification type: {notification}")
    #         _LOGGER.info(f"Received notification data_message: {data_message}")
    #
    #     async def async_listen_notifications(*_):
    #         from push_receiver.push_receiver import PushReceiver
    #
    #         await hass.async_add_executor_job(PushReceiver(push_credentials).listen, async_handle_notification)
    #
    #     hass.data.setdefault(DATA_PUSH_RECEIVERS, {})[config_entry_id] = hass.async_create_background_task(
    #         async_listen_notifications(), name="notification listener"
    #     )

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when its updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Pik Intercom entry"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from custom_components.pik_intercom.config_flow import PikIntercomConfigFlow

    _LOGGER.info(
        f"[{entry.entry_id}] Upgrading configuration version: " f"{entry.version} => {PikIntercomConfigFlow.VERSION}"
    )

    data = dict(entry.data)
    options = dict(entry.options)

    if entry.version < 3:
        if entry.source == SOURCE_IMPORT:
            # @TODO: this is because of CONF_PASSWORD, but we can update it
            _LOGGER.error("Cannot migrate YAML entries below version 3; " "reconfigure integration")
            return False

        options.setdefault(
            CONF_DEVICE_ID,
            entry.entry_id[-16:],
        )
        options.setdefault(
            CONF_INTERCOMS_UPDATE_INTERVAL,
            DEFAULT_INTERCOMS_UPDATE_INTERVAL,
        )
        options.setdefault(
            CONF_CALL_SESSIONS_UPDATE_INTERVAL,
            DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL,
        )
        options.setdefault(
            CONF_AUTH_UPDATE_INTERVAL,
            DEFAULT_AUTH_UPDATE_INTERVAL,
        )
        options.setdefault(
            CONF_VERIFY_SSL,
            True,
        )

    if entry.version < 4:
        options[CONF_PUSH_CREDENTIALS] = None

    entry.version = PikIntercomConfigFlow.VERSION
    hass.config_entries.async_update_entry(entry, data=data, options=options)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Clear authentication updater
        if auth_updater := hass.data.get(DATA_REAUTHENTICATORS, {}).pop(entry.entry_id, None):
            auth_updater()

        # Cancel push receiver
        if push_receiver := hass.data.get(DATA_PUSH_RECEIVERS, {}).pop(entry.entry_id, None):
            push_receiver.cancel()

    return unload_ok
