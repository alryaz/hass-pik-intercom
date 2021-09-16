import asyncio
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

import homeassistant.helpers.config_validation as cv

import voluptuous as vol

from custom_components.pik_intercom.api import PikDomofonAPI, PikDomofonException

_LOGGER = logging.getLogger(__name__)

DOMAIN = "pik_intercom"

DATA_YAML_CONFIG = DOMAIN + "_yaml_config"
DATA_ENTITIES = DOMAIN + "_entities"
DATA_FINAL_CONFIG = DOMAIN + "_final_config"
DATA_UPDATE_LISTENERS = DOMAIN + "_update_listeners"

SUPPORTED_PLATFORMS = ("camera", "switch")

CONFIG_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
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


CONFIG_SCHEMA = vol.Schema(
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
    entry_id = config_entry.entry_id
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
                + f"Удаление записи {entry_id} после удаления из конфигурации YAML"
            )
            hass.async_create_task(hass.config_entries.async_remove(entry_id))
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

    try:
        api_object = PikDomofonAPI(
            username=username,
            password=user_cfg[CONF_PASSWORD],
        )

        await api_object.async_authenticate()

        # Fetch all properties
        await api_object.async_update_properties()

    except PikDomofonException as e:
        _LOGGER.error(log_prefix + "Невозможно выполнить авторизацию" + ": " + repr(e))
        raise ConfigEntryNotReady

    apartments = api_object.apartments

    if not apartments:
        # Cancel setup because no accounts provided
        _LOGGER.warning(log_prefix + "Владения найдены")
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
            raise ConfigEntryNotReady(f"Ошибка при обновлении данных: {exc_first_task}")

    _LOGGER.debug(log_prefix + f"Найдено {len(apartments)} владений")

    api_objects: Dict[str, "PikDomofonAPI"] = hass_data.setdefault(DOMAIN, {})

    # Create placeholders
    api_objects[entry_id] = api_object
    hass_data.setdefault(DATA_ENTITIES, {})[entry_id] = []
    hass_data.setdefault(DATA_FINAL_CONFIG, {})[entry_id] = user_cfg

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
    hass_data.setdefault(DATA_UPDATE_LISTENERS, {})[entry_id] = update_listener

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
        api_object: PikDomofonAPI = hass.data[DOMAIN].pop(entry_id)
        if api_object:
            await api_object.async_close()

        hass.data[DATA_FINAL_CONFIG].pop(entry_id)

        cancel_listener = hass.data[DATA_UPDATE_LISTENERS].pop(entry_id)
        cancel_listener()

        _LOGGER.info(log_prefix + "Интеграция выгружена")

    else:
        _LOGGER.warning(log_prefix + "При выгрузке конфигурации произошла ошибка")

    return unload_ok
