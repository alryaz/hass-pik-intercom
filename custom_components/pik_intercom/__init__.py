__all__ = (
    "CONFIG_SCHEMA",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
    "DOMAIN",
)

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any, Callable, Dict, Final, List, Mapping, Optional, Tuple

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

import homeassistant.helpers.config_validation as cv

import voluptuous as vol

from custom_components.pik_intercom.api import (
    DEFAULT_CLIENT_APP,
    DEFAULT_CLIENT_OS,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_USER_AGENT,
    PikIntercomAPI,
    PikIntercomException,
)
from custom_components.pik_intercom.const import (
    CONF_CLIENT_APP,
    CONF_CLIENT_OS,
    CONF_CLIENT_VERSION,
    CONF_REAUTH_INTERVAL,
    CONF_RETRIEVAL_ERROR_THRESHOLD,
    CONF_USER_AGENT,
    DATA_ENTITIES,
    DATA_ENTITY_UPDATERS,
    DATA_FINAL_CONFIG,
    DATA_REAUTHENTICATORS,
    DATA_UPDATE_LISTENERS,
    DATA_YAML_CONFIG,
    DOMAIN,
    SUPPORTED_PLATFORMS,
    UPDATE_CONFIG_KEY_CALL_SESSIONS,
    UPDATE_CONFIG_KEY_INTERCOMS,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(
            UPDATE_CONFIG_KEY_CALL_SESSIONS,
            default=timedelta(seconds=300),
        ): cv.positive_time_period,
        vol.Optional(
            UPDATE_CONFIG_KEY_INTERCOMS,
            default=timedelta(minutes=30),
        ): cv.positive_time_period,
    }
)


def _phone_validator(phone_number: str) -> str:
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


CONFIG_ENTRY_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_USERNAME): vol.All(
            cv.string, vol.Any(_phone_validator, vol.Email)
        ),
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_SCHEMA({})): vol.Any(
            vol.All(
                cv.positive_time_period,
                lambda x: {str(k): x for k in SCAN_INTERVAL_SCHEMA.schema.keys()},
                SCAN_INTERVAL_SCHEMA,
            ),
            SCAN_INTERVAL_SCHEMA,
        ),
        vol.Optional(CONF_RETRIEVAL_ERROR_THRESHOLD, default=50): vol.All(
            cv.positive_int, vol.Clamp(min=5)
        ),
        vol.Optional(CONF_REAUTH_INTERVAL, default=timedelta(hours=72)): vol.All(
            cv.positive_time_period, vol.Clamp(min=timedelta(hours=12))
        ),
        vol.Optional(CONF_CLIENT_APP, default=DEFAULT_CLIENT_APP): cv.string,
        vol.Optional(CONF_CLIENT_OS, default=DEFAULT_CLIENT_OS): cv.string,
        vol.Optional(CONF_CLIENT_VERSION, default=DEFAULT_CLIENT_VERSION): cv.string,
        vol.Optional(CONF_USER_AGENT, default=DEFAULT_USER_AGENT): cv.string,
        vol.Optional(CONF_DEVICE_ID, default=None): vol.Any(vol.Equal(None), cv.string),
    }
)


def _unique_entries(value: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    users: Dict[Tuple[str, str], Optional[int]] = {}

    errors = []
    for i, config in enumerate(value):
        user = config[CONF_USERNAME]
        if user in users:
            if users[user] is not None:
                errors.append(
                    vol.Invalid(
                        "duplicate unique key, first encounter", path=[users[user]]
                    )
                )
                users[user] = None
            errors.append(
                vol.Invalid("duplicate unique key, subsequent encounter", path=[i])
            )
        else:
            users[user] = i

    if errors:
        if len(errors) > 1:
            raise vol.MultipleInvalid(errors)
        raise next(iter(errors))

    return value


CONFIG_SCHEMA: Final = vol.Schema(
    {
        DOMAIN: vol.Any(
            vol.Equal({}),
            vol.All(
                cv.ensure_list,
                vol.Length(min=1),
                [CONFIG_ENTRY_SCHEMA],
                _unique_entries,
            ),
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@callback
def _find_existing_entry(
    hass: HomeAssistantType, username: str
) -> Optional[config_entries.ConfigEntry]:
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    for config_entry in existing_entries:
        if config_entry.data[CONF_USERNAME] == username:
            return config_entry


_RE_USERNAME_MASK = re.compile(r"^(\W*)(.).*(.)$")


def mask_username(username: str):
    parts = username.split("@")
    return "@".join(map(lambda x: _RE_USERNAME_MASK.sub(r"\1\2***\3", x), parts))


async def async_setup(hass: HomeAssistantType, config: ConfigType):
    """Set up the TNS Energo component."""
    domain_config = config.get(DOMAIN)
    if not domain_config:
        return True

    domain_data = {}
    hass.data[DOMAIN] = domain_data

    yaml_config = {}
    hass.data[DATA_YAML_CONFIG] = yaml_config

    for user_cfg in domain_config:
        if not user_cfg:
            continue

        username: str = user_cfg[CONF_USERNAME]

        key = username
        log_prefix = f"[{mask_username(username)}] "

        _LOGGER.debug(log_prefix + "Получена конфигурация из YAML")

        existing_entry = _find_existing_entry(hass, username)
        if existing_entry:
            if existing_entry.source == config_entries.SOURCE_IMPORT:
                yaml_config[key] = user_cfg
                _LOGGER.debug(
                    log_prefix + "Соответствующая конфигурационная запись существует"
                )
            else:
                _LOGGER.warning(
                    log_prefix
                    + "Конфигурация из YAML переопределена другой конфигурацией!"
                )
            continue

        # Save YAML configuration
        yaml_config[key] = user_cfg

        _LOGGER.warning(log_prefix + "Создание новой конфигурационной записи")

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={CONF_USERNAME: username},
            )
        )

    if not yaml_config:
        _LOGGER.debug("Конфигурация из YAML не обнаружена")

    return True


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry):
    username = config_entry.data[CONF_USERNAME]
    unique_key = username
    config_entry_id = config_entry.entry_id
    log_prefix = f"[{mask_username(username)}] "
    hass_data = hass.data

    _LOGGER.debug(log_prefix + "Setting up config entry")

    # Source full configuration
    if config_entry.source == config_entries.SOURCE_IMPORT:
        # Source configuration from YAML
        yaml_config = hass_data.get(DATA_YAML_CONFIG)

        if not yaml_config or unique_key not in yaml_config:
            _LOGGER.info(
                log_prefix
                + f"Удаление записи {config_entry_id} после удаления из конфигурации YAML"
            )
            hass.async_create_task(hass.config_entries.async_remove(config_entry_id))
            return False

        user_cfg = yaml_config[unique_key]

    else:
        # Source and convert configuration from input post_fields
        all_cfg = {**config_entry.data}

        if config_entry.options:
            all_cfg.update(config_entry.options)

        try:
            user_cfg = CONFIG_ENTRY_SCHEMA(all_cfg)
        except vol.Invalid as e:
            _LOGGER.error(
                log_prefix + "Сохранённая конфигурация повреждена" + ": " + repr(e)
            )
            return False

    _LOGGER.info(log_prefix + "Применение конфигурационной записи")

    device_id = user_cfg.get(CONF_DEVICE_ID)
    if not device_id:
        device_id = config_entry.entry_id[-16:]
        user_cfg[CONF_DEVICE_ID] = device_id
        used_device_id_source = "полученный из ID записи"
    else:
        used_device_id_source = "заданный пользователем"

    _LOGGER.debug(
        log_prefix + f"Используемый device_id: {device_id} ({used_device_id_source})"
    )

    api_object = PikIntercomAPI(
        username=username,
        password=user_cfg[CONF_PASSWORD],
        device_id=device_id,
        client_app=user_cfg[CONF_CLIENT_APP],
        client_os=user_cfg[CONF_CLIENT_OS],
        client_version=user_cfg[CONF_CLIENT_VERSION],
        user_agent=user_cfg[CONF_USER_AGENT],
    )

    try:
        await api_object.async_authenticate()

        # Fetch all properties
        await api_object.async_update_properties()

    except PikIntercomException as e:
        _LOGGER.error(log_prefix + "Невозможно выполнить авторизацию: " + repr(e))
        await api_object.async_close()
        raise ConfigEntryNotReady(f"{e}")

    apartments = api_object.apartments

    if not apartments:
        # Cancel setup because no accounts provided
        _LOGGER.warning(log_prefix + "Владения найдены")
        await api_object.async_close()
        return False

    tasks = []
    for apartment_object in apartments.values():
        tasks.append(apartment_object.async_update_intercoms())

    if tasks:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        if pending:
            for task in pending:
                task.cancel()

        first_task = next(iter(done))
        exc_first_task = first_task.exception()
        if exc_first_task:
            await api_object.async_close()
            raise ConfigEntryNotReady(f"Ошибка при обновлении данных: {exc_first_task}")

    _LOGGER.debug(log_prefix + f"Найдено {len(apartments)} владений")

    api_objects: Dict[str, "PikIntercomAPI"] = hass_data.setdefault(DOMAIN, {})

    # Create placeholders
    api_objects[config_entry_id] = api_object
    hass_data.setdefault(DATA_ENTITIES, {})[config_entry_id] = {}
    hass_data.setdefault(DATA_FINAL_CONFIG, {})[config_entry_id] = user_cfg
    hass_data.setdefault(DATA_ENTITY_UPDATERS, {})[config_entry_id] = {}

    # Forward entry setup to sensor platform
    for domain in SUPPORTED_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(
                config_entry,
                domain,
            )
        )

    # Create options update listener
    update_listener = config_entry.add_update_listener(async_reload_entry)
    hass_data.setdefault(DATA_UPDATE_LISTENERS, {})[config_entry_id] = update_listener

    # Create reauth listener
    async def async_reauthenticate(*_):
        _LOGGER.debug(log_prefix + "Выполнение профилактической реавторизации")

        await api_object.async_authenticate()

    hass.data.setdefault(DATA_REAUTHENTICATORS, {})[
        config_entry_id
    ] = async_track_time_interval(
        hass,
        async_reauthenticate,
        timedelta(days=1),
    )

    _LOGGER.debug(log_prefix + "Применение конфигурации успешно")
    return True


async def async_reload_entry(
    hass: HomeAssistantType,
    config_entry: config_entries.ConfigEntry,
) -> None:
    """Reload Lkcomu TNS Energo entry"""
    log_prefix = f"[{mask_username(config_entry.data[CONF_USERNAME])}] "
    _LOGGER.info(log_prefix + "Перезагрузка интеграции")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistantType, config_entry: ConfigEntry):
    log_prefix = f"[{mask_username(config_entry.data[CONF_USERNAME])}] "
    entry_id = config_entry.entry_id

    tasks = [
        hass.config_entries.async_forward_entry_unload(config_entry, domain)
        for domain in SUPPORTED_PLATFORMS
    ]

    unload_ok = all(await asyncio.gather(*tasks))

    if unload_ok:
        # Cancel entity updaters
        for update_identifier, (cancel_func, _) in (
            hass.data[DATA_ENTITY_UPDATERS].pop(entry_id).items()
        ):
            cancel_func()

        # Cancel reauthentication routines
        reauthenticator: Callable = hass.data.get(DATA_REAUTHENTICATORS, {}).pop(
            entry_id, None
        )
        if reauthenticator:
            reauthenticator()

        # Cancel entry update listeners
        cancel_listener = hass.data[DATA_UPDATE_LISTENERS].pop(entry_id)
        cancel_listener()

        # Close API object
        api_object: PikIntercomAPI = hass.data.get(DOMAIN, {}).pop(entry_id, None)
        if api_object:
            await api_object.async_close()

        # Remove final configuration holder
        hass.data[DATA_FINAL_CONFIG].pop(entry_id)

        # Remove entity holder
        hass.data[DATA_ENTITIES].pop(entry_id)

        _LOGGER.info(log_prefix + "Интеграция выгружена")

    else:
        _LOGGER.warning(log_prefix + "При выгрузке конфигурации произошла ошибка")

    return unload_ok
