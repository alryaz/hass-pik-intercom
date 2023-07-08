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
    ConfigEntryLoggerAdapter,
    AnyLogger,
    get_logger,
    async_get_authenticated_api,
    async_change_device_prefix,
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
        vol.Optional(
            CONF_ADD_SUGGESTED_AREAS, default=DEFAULT_ADD_SUGGESTED_AREAS
        ): cv.boolean,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
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
        entry.data.get(CONF_USERNAME): entry
        for entry in hass.config_entries.async_entries(DOMAIN)
    }
    for user_cfg in domain_config:
        if entry := configured_users.get(user_cfg[CONF_USERNAME]):
            if entry.data.get(CONF_PASSWORD) != user_cfg[CONF_PASSWORD]:
                _LOGGER.info(f"Migrating password for entry {entry.entry_id}")
                hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_cfg[CONF_PASSWORD],
                    },
                )
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
    *,
    logger: AnyLogger = _LOGGER,
) -> list[BasePikUpdateCoordinator]:
    logger = get_logger(logger)

    # Update properties
    try:
        await api_object.icm_update_properties()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        msg = f"Невозможно получить данные владений: {exc}"
        logger.error(msg, exc_info=exc)
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
        logger.error(msg)
        raise ConfigEntryNotReady(msg) from exc

    # Return if no intercoms exist
    if not (icm_intercoms := api_object.icm_intercoms):
        logger.warning(
            "Will not update ICM intercoms because "
            "none fetched on initial request"
        )
        return []

    # Calculate ICM refresh interval
    if (interval := entry.options[CONF_INTERCOMS_UPDATE_INTERVAL]) > 0:
        interval = timedelta(
            seconds=max(MIN_INTERCOMS_UPDATE_INTERVAL, interval)
        )
        logger.debug(f"Setting up ICM updates with interval: {interval}")
    else:
        interval = None
        logger.debug("Not setting up ICM updates")

    if entry.options.get(CONF_ICM_SEPARATE_UPDATES):
        # Setup discrete updates using intercom update coordinators
        return [
            PikIcmIntercomUpdateCoordinator(
                hass,
                api_object=api_object,
                object_id=intercom_id,
                update_interval=interval,
            )
            for intercom_id in icm_intercoms
        ]

    # Find building data (needed only for suggested areas)
    if entry.options.get(CONF_ADD_SUGGESTED_AREAS):
        building_ids = {
            intercom.building_id
            for intercom in api_object.icm_intercoms.values()
            if intercom.building_id is not None
        }

        if building_ids:
            tasks = [
                hass.loop.create_task(
                    api_object.icm_update_building(building_id)
                )
                for building_id in building_ids
            ]
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in pending:
                task.cancel()
            if exc := next(iter(done)).exception():
                logger.error(
                    f"Error while fetching buildings: {exc}", exc_info=exc
                )
                raise ConfigEntryNotReady from exc

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
        logger.debug(f"Will filter properties between: {valid_property_ids}")
        while property_intercom_ids:
            property_id, intercom_ids = property_intercom_ids.pop()
            if any(
                intercom_ids.issubset(other_ids)
                for _, other_ids in property_intercom_ids
            ):
                logger.debug(f"Skipping redundant property: {property_id}")
                valid_property_ids.remove(property_id)

    # Setup ICM property updates
    return [
        PikIcmPropertyUpdateCoordinator(
            hass,
            api_object=api_object,
            object_id=property_id,
            update_interval=interval,
        )
        for property_id in valid_property_ids
    ]


async def async_init_iot_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api_object: PikIntercomAPI,
    *,
    logger: AnyLogger = _LOGGER,
) -> list[BasePikUpdateCoordinator]:
    logger = get_logger(logger)

    if (interval := entry.options[CONF_IOT_UPDATE_INTERVAL]) > 0:
        interval = timedelta(seconds=max(MIN_IOT_UPDATE_INTERVAL, interval))
        logger.debug(
            f"Setting up IoT devices updates with interval: {interval}"
        )
    else:
        interval = None
        logger.debug("Not setting up IoT device updates")

    return [
        coordinator_cls(
            hass,
            api_object=api_object,
            update_interval=interval,
        )
        for coordinator_cls in (
            PikIotCamerasUpdateCoordinator,
            PikIotMetersUpdateCoordinator,
            PikIotIntercomsUpdateCoordinator,
        )
    ]


async def async_init_lcs_coordinator(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api_object: PikIntercomAPI,
    *,
    logger: AnyLogger = _LOGGER,
) -> PikLastCallSessionUpdateCoordinator | None:
    logger = get_logger(logger)

    if (interval := entry.options[CONF_LAST_CALL_SESSION_UPDATE_INTERVAL]) > 0:
        interval = timedelta(
            seconds=max(
                MIN_LAST_CALL_SESSION_UPDATE_INTERVAL,
                interval,
            )
        )
        logger.debug(
            f"Setting up last call session updates with interval: {interval}"
        )
    else:
        interval = None
        logger.debug("Not setting up last call session updates")

    return PikLastCallSessionUpdateCoordinator(
        hass, api_object=api_object, update_interval=interval
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger = get_logger(_LOGGER)

    api_object = await async_get_authenticated_api(hass, entry, logger=logger)

    try:
        await api_object.update_customer_device()
    except PikIntercomException as exc:
        msg = f"Невозможно выполнить обновление данных клиентского устройства: {exc}"
        logger.error(msg, exc_info=exc)
        raise ConfigEntryAuthFailed(msg) from exc

    # initialize coordinator objects
    coordinators = [
        await async_init_lcs_coordinator(
            hass, entry, api_object, logger=logger
        )
    ]
    coordinators.extend(
        await async_init_iot_coordinators(
            hass, entry, api_object, logger=logger
        )
    )
    coordinators.extend(
        await async_init_icm_coordinators(
            hass, entry, api_object, logger=logger
        )
    )

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
        logger.debug("Performing reauthentication")

        await api_object.authenticate()

    if (interval := entry.options[CONF_AUTH_UPDATE_INTERVAL]) > 0:
        interval = timedelta(seconds=max(MIN_AUTH_UPDATE_INTERVAL, interval))
        logger.debug(f"Setting up reauthentication with interval: {interval}")
        hass.data.setdefault(DATA_REAUTHENTICATORS, {})[
            entry.entry_id
        ] = async_track_time_interval(
            hass,
            async_reauthenticate,
            interval,
        )
    else:
        logger.debug("Will not setup reauthentication")

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when its updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Pik Intercom entry"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Migrate configuration entry to new version.
    :param hass: Home Assistant object
    :param entry: Configuration entry
    :return: Migration status
    """
    logger = get_logger(_LOGGER)

    from custom_components.pik_intercom.config_flow import (
        PikIntercomConfigFlow,
    )

    logger.info(
        f"Upgrading configuration version: {entry.version} => {PikIntercomConfigFlow.VERSION}"
    )

    data = dict(entry.data)
    options = dict(entry.options)
    args = {"data": data, "options": options}

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

        async_change_device_prefix(
            hass, entry, "property_intercom__", "icm_intercom__", logger=logger
        )

    if entry.version < 8:
        api_object = await async_get_authenticated_api(
            hass, entry, logger=logger
        )

        args["unique_id"] = str(api_object.account.id)

        async_change_device_prefix(
            hass,
            entry,
            f"last_call_session__{entry.entry_id}",
            f"last_call_session__{api_object.account.id}",
            logger=logger,
        )

    entry.version = PikIntercomConfigFlow.VERSION
    hass.config_entries.async_update_entry(entry, **args)

    logger.info(f"Migration to version {entry.version} successful!")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload configuration entry
    :param hass: Home Assistant object
    :param entry: Configuration entry
    :return: Unload status
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        all_entities = hass.data.get(DATA_ENTITIES, {})
        for entity_cls in tuple(all_entities):
            entities_dict = all_entities[entity_cls]
            for key in tuple(entities_dict):
                try:
                    entity_entry_id = entities_dict[
                        key
                    ].coordinator.config_entry.entry_id
                except AttributeError:
                    pass
                else:
                    if entity_entry_id == entry.entry_id:
                        del entities_dict[key]
            if not entities_dict:
                del all_entities[entity_cls]

        # Remove coordinator
        hass.data.get(DOMAIN, {}).pop(entry.entry_id)

        # Clear authentication updater
        if auth_updater := hass.data.get(DATA_REAUTHENTICATORS, {}).pop(
            entry.entry_id, None
        ):
            auth_updater()

    return unload_ok
