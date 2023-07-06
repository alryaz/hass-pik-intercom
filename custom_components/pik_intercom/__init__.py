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

from custom_components.pik_intercom.const import *
from custom_components.pik_intercom.entity import (
    BasePikUpdateCoordinator,
    PikIcmIntercomUpdateCoordinator,
    PikIotIntercomsUpdateCoordinator,
    PikIotCamerasUpdateCoordinator,
    PikIotMetersUpdateCoordinator,
    PikLastCallSessionUpdateCoordinator,
    PikIcmPropertyUpdateCoordinator,
)
from custom_components.pik_intercom.helpers import (
    phone_validator,
    patch_haffmpeg,
)
from pik_intercom import PikIntercomAPI, PikIntercomException

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


async def async_init_icm_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api_object: PikIntercomAPI,
) -> list[BasePikUpdateCoordinator]:
    eid = entry.entry_id[-6:]
    # Update properties
    try:
        await api_object.icm_update_properties()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        msg = f"Невозможно получить данные владений: {exc}"
        _LOGGER.error(f"[{eid}] {exc}", exc_info=exc)
        raise ConfigEntryNotReady(msg) from exc

    # Return if no properties exist
    if not api_object.icm_properties:
        return []

    # Update intercoms for all properties
    try:
        await api_object.icm_update_intercoms()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        msg = f"Невозможно получить данные о домофонах: {exc}"
        _LOGGER.error(f"[{eid}] {exc}", exc_info=exc)
        raise ConfigEntryNotReady(msg) from exc

    # Return if no intercoms exist
    if not (icm_intercoms := api_object.icm_intercoms):
        return []

    # Calculate ICM refresh interval
    if (interval := entry.options[CONF_INTERCOMS_UPDATE_INTERVAL]) > 0:
        interval = timedelta(
            seconds=max(MIN_INTERCOMS_UPDATE_INTERVAL, interval)
        )
        _LOGGER.debug(
            f"[{eid}] Setting up ICM updates with interval: {interval}"
        )
    else:
        interval = None
        _LOGGER.debug(f"[{eid}] Not setting up ICM updates")

    if entry.options.get(CONF_ICM_SEPARATE_UPDATES):
        # Setup discrete updates using intercom update coordinators
        return [
            PikIcmIntercomUpdateCoordinator(
                hass,
                api_object=api_object,
                intercom_id=intercom_id,
                update_interval=interval,
            )
            for intercom_id in icm_intercoms
        ]

    # Rule out required properties
    valid_property_ids = list(api_object.icm_properties.keys())
    if len(valid_property_ids) > 1:
        property_intercom_ids = [
            (
                property_id,
                set(api_object.icm_properties[property_id].intercoms.keys()),
            )
            for property_id in valid_property_ids
        ]

        # Iterate of intercom ids to find out
        # which properties contain the same and/or greater options.
        #
        # This is a dead-simple method; if you know how to improve
        # it please create an issue!
        _LOGGER.debug(
            f"[{eid}] Will filter out redundant properties between: {valid_property_ids}"
        )
        while property_intercom_ids:
            property_id, intercom_ids = property_intercom_ids.pop()
            if any(
                intercom_ids.issubset(other_ids)
                for _, other_ids in property_intercom_ids
            ):
                _LOGGER.debug(
                    f"[{eid}] Will not update redundant property {property_id}"
                )
                valid_property_ids.remove(property_id)

    # Setup ICM property updates
    return [
        PikIcmPropertyUpdateCoordinator(
            hass,
            api_object=api_object,
            property_id=property_id,
            update_interval=interval,
        )
        for property_id in valid_property_ids
    ]


async def async_init_iot_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api_object: PikIntercomAPI,
) -> list[BasePikUpdateCoordinator]:
    eid = entry.entry_id[-6:]
    possible_tasks = {
        PikIotCamerasUpdateCoordinator: api_object.iot_update_cameras(),
        PikIotMetersUpdateCoordinator: api_object.iot_update_meters(),
        PikIotIntercomsUpdateCoordinator: api_object.iot_update_intercoms(),
    }

    if (interval := entry.options[CONF_IOT_UPDATE_INTERVAL]) > 0:
        interval = timedelta(seconds=max(MIN_IOT_UPDATE_INTERVAL, interval))
        _LOGGER.debug(
            f"[{eid}] Setting up IoT devices updates with interval: {interval}"
        )
    else:
        interval = None
        _LOGGER.debug(f"[{eid}] Not setting up IoT devices updates")

    tasks = [
        hass.loop.create_task(coroutine)
        for coroutine in possible_tasks.values()
    ]

    done, pending = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_EXCEPTION
    )
    for task in pending:
        task.cancel()

    coordinators = []
    for coordinator_cls, task in zip(possible_tasks, done):
        if exc := task.exception():
            msg = f"Невозможно получить данные об устройствах: {exc}"
            _LOGGER.error(f"[{eid}] {exc}", exc_info=exc)
            raise ConfigEntryNotReady(msg) from exc
        coordinators.append(
            coordinator_cls(
                hass, api_object=api_object, update_interval=interval
            )
        )

    return coordinators


async def async_init_lcs_coordinator(
    hass: HomeAssistant, entry: ConfigEntry, api_object: PikIntercomAPI
) -> PikLastCallSessionUpdateCoordinator | None:
    eid = entry.entry_id[-6:]
    if (interval := entry.options[CONF_LAST_CALL_SESSION_UPDATE_INTERVAL]) > 0:
        interval = timedelta(
            seconds=max(
                MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
                interval,
            )
        )
        _LOGGER.debug(
            f"[{eid}] Setting up last call session updates with interval: {interval}"
        )
    else:
        interval = None
        _LOGGER.debug(f"[{eid}] Not setting up last call session updates")

    return PikLastCallSessionUpdateCoordinator(
        hass, api_object=api_object, update_interval=interval
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    eid = entry.entry_id[-6:]

    api_object = PikIntercomAPI(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
        device_id=entry.options[CONF_DEVICE_ID],
    )

    try:
        await api_object.authenticate()
        await api_object.update_customer_device()
    except PikIntercomException as exc:
        msg = f"Невозможно выполнить авторизацию: {exc}"
        _LOGGER.error(f"[{eid}] {msg}", exc_info=exc)
        raise ConfigEntryAuthFailed(msg) from exc

    coordinators = [
        *(await async_init_iot_coordinators(hass, entry, api_object)),
        *(await async_init_icm_coordinators(hass, entry, api_object)),
        await async_init_lcs_coordinator(hass, entry, api_object),
    ]

    # Perform initial update tasks
    done, pending = await asyncio.wait(
        [
            hass.loop.create_task(
                coordinator.async_config_entry_first_refresh()
            )
            for coordinator in coordinators
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
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    hass.data.setdefault(DATA_ENTITIES, {})

    # Create automatic authentication updater
    async def async_reauthenticate(*_):
        _LOGGER.debug(f"[{eid}] Performing reauthentication")

        await api_object.authenticate()

    if (interval := entry.options[CONF_AUTH_UPDATE_INTERVAL]) > 0:
        interval = timedelta(seconds=max(MIN_AUTH_UPDATE_INTERVAL, interval))
        _LOGGER.debug(
            f"[{eid}] Setting up reauthentication with interval: {interval}"
        )
        hass.data.setdefault(DATA_REAUTHENTICATORS, {})[
            entry.entry_id
        ] = async_track_time_interval(
            hass,
            async_reauthenticate,
            interval,
        )
    else:
        _LOGGER.debug(f"[{eid}] Will not setup reauthentication")

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

    eid = entry.entry_id[-6:]

    _LOGGER.info(
        f"[{eid}] Upgrading configuration version: {entry.version} => {PikIntercomConfigFlow.VERSION}"
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

    if entry.version < 7:
        options.setdefault(
            CONF_ICM_SEPARATE_UPDATES, DEFAULT_ICM_SEPARATE_UPDATES
        )

        from homeassistant.helpers.entity_registry import (
            async_get,
            async_entries_for_config_entry,
        )

        ent_reg = async_get(hass)
        for ent in async_entries_for_config_entry(ent_reg, entry.entry_id):
            if not ent.unique_id.startswith("property_intercom__"):
                continue
            new_unique_id = "icm_intercom__" + ent.unique_id[19:]
            _LOGGER.debug(
                f"[{eid}] Updated unique ID: {ent.unique_id} => {new_unique_id}"
            )
            ent_reg.async_update_entity(
                ent.entity_id, new_unique_id=new_unique_id
            )

        from homeassistant.helpers.device_registry import (
            async_get,
            async_entries_for_config_entry,
        )

        dev_reg = async_get(hass)
        for dev in async_entries_for_config_entry(dev_reg, entry.entry_id):
            new_identifiers = set()
            for first_part, second_part in dev.identifiers:
                if first_part == DOMAIN and second_part.startswith(
                    "property_intercom__"
                ):
                    new_second_part = "icm_intercom__" + second_part[19:]
                    _LOGGER.debug(
                        f"[{eid}] Updated dev ID: {second_part} => {new_second_part}"
                    )
                    second_part = new_second_part
                new_identifiers.add((first_part, second_part))
            if dev.identifiers == new_identifiers:
                continue
            dev_reg.async_update_device(
                dev.id,
                new_identifiers=new_identifiers,
            )

    entry.version = PikIntercomConfigFlow.VERSION
    hass.config_entries.async_update_entry(entry, data=data, options=options)

    _LOGGER.info(f"[{eid}] Migration to version {entry.version} successful!")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        # Remove coordinator
        hass.data.get(DOMAIN, {}).pop(entry.entry_id)

        # Clear authentication updater
        if auth_updater := hass.data.get(DATA_REAUTHENTICATORS, {}).pop(
            entry.entry_id, None
        ):
            auth_updater()

    return unload_ok
