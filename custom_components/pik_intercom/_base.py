import asyncio
import logging
import re
from abc import ABC
from typing import Any, ClassVar, Dict, Final, Tuple, Hashable

import voluptuous as vol
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.api import PikIntercomAPI, PikIntercomDevice
from custom_components.pik_intercom.const import (
    CONF_INTERCOMS_UPDATE_INTERVAL,
    DATA_ENTITIES,
    DATA_ENTITY_UPDATERS,
    DATA_FINAL_CONFIG,
    DOMAIN,
    UPDATE_CONFIG_KEY_INTERCOMS,
)

_LOGGER: Final = logging.getLogger(__name__)


class BasePikIntercomEntity(Entity, ABC):
    def __init__(self, hass: HomeAssistantType, config_entry_id: str) -> None:
        self.hass = hass
        self._config_entry_id = config_entry_id

    @property
    def api_object(self) -> PikIntercomAPI:
        hass = self.hass
        assert hass, "Home Assistant object not loaded"

        domain_data = self.hass.data.get(DOMAIN)
        assert domain_data, "Domain data is empty"

        api_object = domain_data.get(self._config_entry_id)
        assert api_object, "API object is missing"

        return api_object

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        self.hass.data[DATA_ENTITIES][self._config_entry_id].append(self)

    async def async_will_remove_from_hass(self) -> None:
        entities = self.hass.data[DATA_ENTITIES][self._config_entry_id]

        if self in entities:
            entities.remove(self)


class BasePikIntercomDeviceEntity(BasePikIntercomEntity):
    _intercom_getter_futures: ClassVar[Dict[Tuple[str, int], asyncio.Future]] = {}

    @property
    def device_info(self) -> Dict[str, Any]:
        intercom_device = self._intercom_device

        return {
            "name": intercom_device.name,
            "manufacturer": intercom_device.device_category,
            "model": intercom_device.kind + " / " + intercom_device.mode,
            "identifiers": {(DOMAIN, intercom_device.id)},
            "suggested_area": f"Property {intercom_device.property_id}",
        }

    @classmethod
    async def async_update_data(
        cls,
        hass: HomeAssistantType,
        config_entry_id: str,
        property_id: int,
    ) -> None:
        futures = cls._intercom_getter_futures
        future_key = (config_entry_id, property_id)
        log_prefix = f"[{config_entry_id}] "
        if future_key in futures:
            _LOGGER.debug(log_prefix + f"Ожидание обновления intercoms[{property_id}]")
            return await futures[future_key]

        _LOGGER.debug(log_prefix + f"Выполнение обновления intercoms[{property_id}]")

        api_object: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]
        future = hass.loop.create_future()
        futures[future_key] = future

        try:
            await api_object.async_update_property_intercoms(property_id)
        except BaseException as error:
            future.set_exception(error)
            _LOGGER.error(log_prefix + f"Ошибка при обновлении intercoms[{property_id}]: {error}")

            raise future.exception()
        else:
            _LOGGER.debug(log_prefix + f"Обновление intercoms[{property_id}] завершено")
            future.set_result(None)
        finally:
            del futures[future_key]

    async def async_update(self) -> None:
        await self.async_update_data(
            self.hass,
            self._config_entry_id,
            self._intercom_device.property_id,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        hass = self.hass
        property_id = self._intercom_device.property_id
        config_entry_id = self._config_entry_id
        updaters = hass.data[DATA_ENTITY_UPDATERS][config_entry_id]
        update_key = f"property_{property_id}_intercoms"

        if update_key in updaters:
            return None

        interval = hass.data[DATA_FINAL_CONFIG][config_entry_id][CONF_INTERCOMS_UPDATE_INTERVAL]

        _LOGGER.debug(
            f"[{config_entry_id}] Scheduling intercoms[{property_id}] updates "
            f"with {interval.total_seconds()} seconds interval"
        )

        async def _async_update_property_intercoms(*_):
            await BasePikIntercomDeviceEntity.async_update_data(
                hass,
                config_entry_id,
                property_id,
            )

        updaters[update_key] = async_track_time_interval(
            hass,
            _async_update_property_intercoms,
            interval,
        )

    @property
    def intercom_property_id(self) -> int:
        return self._intercom_device.property_id

    def __init__(
        self,
        hass: HomeAssistantType,
        config_entry_id: str,
        intercom_device: PikIntercomDevice,
    ) -> None:
        super().__init__(hass, config_entry_id)

        self._intercom_device: PikIntercomDevice = intercom_device

    @property
    def available(self) -> bool:
        my_intercom_device = self._intercom_device
        for intercom_device in self.api_object.devices.values():
            if intercom_device is my_intercom_device:
                return True
        return False

    @property
    def update_config_key(self) -> str:
        return UPDATE_CONFIG_KEY_INTERCOMS

    @property
    def update_identifier(self) -> Hashable:
        return self._intercom_device.property_id


def phone_validator(phone_number: str) -> str:
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
        raise vol.Invalid(f"Irregular phone number length (expected 11, got {len(phone_number)})")
