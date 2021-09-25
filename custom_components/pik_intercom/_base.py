import logging
from abc import ABC, abstractmethod
from collections import Hashable
from typing import List, Tuple

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval

from custom_components.pik_intercom.const import (
    DATA_ENTITIES,
    DATA_ENTITY_UPDATERS,
    DATA_FINAL_CONFIG,
    DOMAIN,
    UPDATE_CONFIG_KEY_INTERCOMS,
)
from custom_components.pik_intercom.api import PikIntercomAPI, PikIntercomDevice


_LOGGER = logging.getLogger(__name__)


class BasePikIntercomEntity(Entity, ABC):
    def __init__(self, config_entry_id: str) -> None:
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

    async def async_added_to_hass(self) -> None:
        hass_data = self.hass.data
        config_entry_id = self._config_entry_id
        update_data_key = self._update_data_key

        update_entities: List[BasePikIntercomEntity] = hass_data[DATA_ENTITIES][
            config_entry_id
        ].setdefault(update_data_key, [])

        update_entities.append(self)

        if update_data_key in hass_data[DATA_ENTITY_UPDATERS][config_entry_id]:
            return

        async def _async_update_entities(*_) -> None:
            try:
                update_entity = update_entities[0]
            except IndexError:
                _LOGGER.warning(
                    "No entities to update. Did the component offload correctly?"
                )
                return
            else:
                # noinspection PyUnresolvedReferences
                await update_entity.async_update_internal()
                for entity in update_entities:
                    entity.async_schedule_update_ha_state(False)

        time_interval = hass_data[DATA_FINAL_CONFIG][self._config_entry_id][
            CONF_SCAN_INTERVAL
        ][self.update_config_key]

        _LOGGER.debug(
            f"Scheduling {update_data_key} entity updater "
            f"with {time_interval.total_seconds()} interval"
        )
        updater = async_track_time_interval(
            self.hass, _async_update_entities, time_interval
        )
        hass_data[DATA_ENTITY_UPDATERS][config_entry_id][update_data_key] = (
            updater,
            _async_update_entities,
        )

    async def async_will_remove_from_hass(self) -> None:
        update_entities = (
            self.hass.data.get(DATA_ENTITIES, {})
            .get(self._config_entry_id, {})
            .get(self._update_data_key, [])
        )

        if self in update_entities:
            update_entities.remove(self)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    @abstractmethod
    def update_identifier(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def update_config_key(self) -> str:
        raise NotImplementedError

    @property
    def _update_data_key(self) -> Tuple[str, str]:
        return self.update_config_key, self.update_identifier

    @abstractmethod
    async def async_update_internal(self) -> None:
        raise NotImplementedError

    async def async_update(self) -> None:
        try:
            cancel_func, update_func = self.hass.data[DATA_ENTITY_UPDATERS][
                self._config_entry_id
            ][self._update_data_key]
        except KeyError:
            _LOGGER.debug(f"Using raw updater to update entity {self.entity_id}")
            update_func = self.async_update_internal
        await update_func()


class BasePikIntercomDeviceEntity(BasePikIntercomEntity):
    def __init__(
        self, config_entry_id: str, intercom_device: PikIntercomDevice
    ) -> None:
        super().__init__(config_entry_id)
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

    async def async_update_internal(self) -> None:
        await self.api_object.async_update_property_intercoms(
            self._intercom_device.property_id
        )
