import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Final, Tuple, Hashable, Optional

import voluptuous as vol
from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikPropertyDevice,
    PikIotRelay,
    PikIotIntercom,
)
from custom_components.pik_intercom.const import (
    CONF_INTERCOMS_UPDATE_INTERVAL,
    DATA_ENTITIES,
    DATA_ENTITY_UPDATERS,
    DATA_FINAL_CONFIG,
    DOMAIN,
)

_LOGGER: Final = logging.getLogger(__name__)


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
        raise vol.Invalid(
            f"Irregular phone number length (expected 11, got {len(phone_number)})"
        )


class BasePikIntercomEntity(Entity, ABC):
    _attr_should_poll = False

    @property
    @abstractmethod
    def _internal_object_identifier(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def base_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def async_self_update(self) -> None:
        raise NotImplementedError

    def __init__(self, hass: HomeAssistantType, config_entry_id: str) -> None:
        self.hass = hass
        self._config_entry_id = config_entry_id

    @property
    def _device_group_identifier(self) -> str:
        return self._internal_object_identifier

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
    def name(self) -> str:
        return self.base_name

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "name": self.base_name,
            "identifiers": {(DOMAIN, self._device_group_identifier)},
        }

    async def async_added_to_hass(self) -> None:
        self.hass.data[DATA_ENTITIES][self._config_entry_id].append(self)

    async def async_will_remove_from_hass(self) -> None:
        entities = self.hass.data[DATA_ENTITIES][self._config_entry_id]

        if self in entities:
            entities.remove(self)

    async def async_update(self) -> None:
        await self.async_self_update()


class BasePikIntercomPropertyDeviceEntity(BasePikIntercomEntity):
    _intercom_getter_futures: ClassVar[
        Dict[Tuple[str, int], asyncio.Future]
    ] = {}

    @property
    def _internal_object_identifier(self) -> str:
        return f"property_intercom__{self._intercom_device.id}"

    @property
    def base_name(self) -> str:
        """Return the name of this camera."""
        intercom_device = self._intercom_device
        return (
            intercom_device.renamed_name
            or intercom_device.human_name
            or intercom_device.name
            or "Intercom " + str(intercom_device.id)
        )

    @property
    def device_info(self) -> DeviceInfo:
        device_info = super().device_info

        intercom_device = self._intercom_device
        device_info.update(
            {
                "manufacturer": intercom_device.device_category,
                "model": intercom_device.kind + " / " + intercom_device.mode,
                "suggested_area": f"Property {intercom_device.property_id}",
            }
        )

        return device_info

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        state_attributes = super().extra_state_attributes or {}

        intercom_device = self._intercom_device
        state_attributes.update(
            {
                "id": intercom_device.id,
                "scheme_id": intercom_device.scheme_id,
                "building_id": intercom_device.building_id,
                "property_id": intercom_device.property_id,
                "device_category": intercom_device.device_category,
                "kind": intercom_device.kind,
                "mode": intercom_device.mode,
                "original_name": intercom_device.name,
                "human_name": intercom_device.human_name,
                "custom_name": intercom_device.renamed_name,
                "relays": intercom_device.relays,
                "checkpoint_relay_index": intercom_device.checkpoint_relay_index,
                "entrance": intercom_device.entrance,
                # "sip_account": intercom_device.sip_account,
                # "can_address": intercom_device.can_address,
            }
        )

        return state_attributes

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
            _LOGGER.debug(
                log_prefix + f"Ожидание обновления intercoms[{property_id}]"
            )
            return await futures[future_key]

        _LOGGER.debug(
            log_prefix + f"Выполнение обновления intercoms[{property_id}]"
        )

        api_object: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]
        future = hass.loop.create_future()
        futures[future_key] = future

        try:
            await api_object.async_update_property_intercoms(property_id)
        except BaseException as error:
            future.set_exception(error)
            _LOGGER.error(
                log_prefix
                + f"Ошибка при обновлении intercoms[{property_id}]: {error}"
            )

            raise future.exception()
        else:
            _LOGGER.debug(
                log_prefix + f"Обновление intercoms[{property_id}] завершено"
            )
            future.set_result(None)
        finally:
            del futures[future_key]

    async def async_self_update(self) -> None:
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

        interval = hass.data[DATA_FINAL_CONFIG][config_entry_id][
            CONF_INTERCOMS_UPDATE_INTERVAL
        ]

        _LOGGER.debug(
            f"[{config_entry_id}] Scheduling intercoms[{property_id}] updates "
            f"with {interval.total_seconds()} seconds interval"
        )

        async def _async_update_property_intercoms(*_):
            await BasePikIntercomPropertyDeviceEntity.async_update_data(
                hass,
                config_entry_id,
                property_id,
            )

        updaters[update_key] = async_track_time_interval(
            hass,
            _async_update_property_intercoms,
            interval,
        )

    def __init__(
        self,
        hass: HomeAssistantType,
        config_entry_id: str,
        intercom_device: PikPropertyDevice,
    ) -> None:
        self._intercom_device: PikPropertyDevice = intercom_device

        super().__init__(hass, config_entry_id)

    @property
    def available(self) -> bool:
        my_intercom_device = self._intercom_device
        for intercom_device in self.api_object.devices.values():
            if intercom_device is my_intercom_device:
                return True
        return False


class BasePikIntercomIotEntity(BasePikIntercomEntity, ABC):
    _iot_intercoms_getter_futures: ClassVar[Dict[str, asyncio.Future]] = {}

    @classmethod
    async def async_update_data(
        cls,
        hass: HomeAssistantType,
        config_entry_id: str,
    ) -> None:
        futures = cls._iot_intercoms_getter_futures
        log_prefix = f"[{config_entry_id}] "

        if config_entry_id in futures:
            _LOGGER.debug(log_prefix + f"Ожидание обновления iot_intercoms]")
            return await futures[config_entry_id]

        _LOGGER.debug(log_prefix + f"Выполнение обновления iot_intercoms")

        api_object: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]
        future = hass.loop.create_future()
        futures[config_entry_id] = future

        try:
            await api_object.async_update_personal_intercoms()
        except BaseException as error:
            future.set_exception(error)
            _LOGGER.error(
                log_prefix + f"Ошибка при обновлении iot_intercoms: {error}"
            )

            raise future.exception()
        else:
            _LOGGER.debug(log_prefix + f"Обновление iot_intercoms завершено")
            future.set_result(None)
        finally:
            del futures[config_entry_id]

    async def async_self_update(self) -> None:
        await self.async_update_data(
            self.hass,
            self._config_entry_id,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        hass = self.hass
        config_entry_id = self._config_entry_id
        updaters = hass.data[DATA_ENTITY_UPDATERS][config_entry_id]
        update_key = f"iot_intercoms"

        if update_key in updaters:
            return None

        interval = hass.data[DATA_FINAL_CONFIG][config_entry_id][
            CONF_INTERCOMS_UPDATE_INTERVAL
        ]

        _LOGGER.debug(
            f"[{config_entry_id}] Scheduling iot_intercoms updates "
            f"with {interval.total_seconds()} seconds interval"
        )

        async def _async_update_property_intercoms(*_):
            await BasePikIntercomIotEntity.async_update_data(
                hass,
                config_entry_id,
            )

        updaters[update_key] = async_track_time_interval(
            hass,
            _async_update_property_intercoms,
            interval,
        )


class BasePikIntercomIotIntercomEntity(BasePikIntercomIotEntity):
    def __init__(
        self,
        hass: HomeAssistantType,
        config_entry_id: str,
        iot_intercom: PikIotIntercom,
    ) -> None:
        self._iot_intercom = iot_intercom

        super().__init__(hass, config_entry_id)

    @property
    def _internal_object_identifier(self) -> str:
        return f"iot_intercom__{self._iot_intercom.id}"

    @property
    def base_name(self) -> str:
        iot_intercom = self._iot_intercom
        return iot_intercom.name or f"IoT Intercom {iot_intercom.id}"

    @property
    def available(self) -> bool:
        my_iot_intercom = self._iot_intercom
        for iot_intercom in self.api_object.iot_intercoms.values():
            if iot_intercom is my_iot_intercom:
                return True
        return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        state_attributes = super().extra_state_attributes or {}

        iot_intercom = self._iot_intercom
        state_attributes.update(
            {
                "id": iot_intercom.id,
                "face_detection": iot_intercom.face_detection,
            }
        )

        return state_attributes

    @property
    def device_info(self) -> DeviceInfo:
        device_info = super().device_info or {}

        geo_unit = self._iot_intercom.geo_unit

        if geo_unit:
            device_info["suggested_area"] = f"Property {geo_unit.id}"

        return device_info


class BasePikIntercomIotRelayEntity(BasePikIntercomIotEntity):
    def __init__(
        self,
        hass: HomeAssistantType,
        config_entry_id: str,
        iot_relay: PikIotRelay,
    ) -> None:
        self._iot_relay = iot_relay

        super().__init__(hass, config_entry_id)

    @property
    def related_iot_intercom(self) -> Optional[PikIotIntercom]:
        my_iot_relay = self._iot_relay
        for iot_intercom in self.api_object.iot_intercoms.values():
            for iot_relay in iot_intercom.relays or ():
                if iot_relay is my_iot_relay:
                    return iot_intercom
        return None

    @property
    def _device_group_identifier(self) -> str:
        iot_intercom = self.related_iot_intercom
        if iot_intercom:
            return f"iot_intercom__{iot_intercom.id}"

        _LOGGER.warning(
            f"[{self}] Unbound IoT relay detected!!! "
            f"Please, report it to the developer."
        )
        return f"iot_relay__{self._iot_relay.id}"

    @property
    def _internal_object_identifier(self) -> str:
        return f"iot_relay__{self._iot_relay.id}"

    @property
    def base_name(self) -> str:
        iot_relay = self._iot_relay
        return iot_relay.friendly_name or f"IoT Relay {iot_relay.id}"

    @property
    def available(self) -> bool:
        my_iot_relay = self._iot_relay
        for intercom_device in self.api_object.iot_relays.values():
            if intercom_device is my_iot_relay:
                return True
        return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        state_attributes = super().extra_state_attributes or {}

        iot_relay = self._iot_relay
        user_settings = iot_relay.user_settings
        state_attributes.update(
            {
                "id": iot_relay.id,
                "original_name": iot_relay.name,
                "custom_name": user_settings.custom_name,
                "is_favorite": user_settings.is_favorite,
                "is_hidden": user_settings.is_hidden,
            }
        )

        return state_attributes

    @property
    def device_info(self) -> DeviceInfo:
        device_info = super().device_info or {}

        geo_unit = self._iot_relay.geo_unit

        if not geo_unit:
            iot_intercom = self.related_iot_intercom
            if iot_intercom:
                geo_unit = iot_intercom.geo_unit

        if geo_unit:
            device_info["suggested_area"] = f"Property {geo_unit.id}"

        return device_info
