"""Pik Intercom switches."""

__all__ = ("async_setup_entry", "PikIntercomUnlockerSwitch")

import asyncio
import logging
from abc import abstractmethod, ABC
from typing import Any, Mapping, Optional, Hashable, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom._base import BasePikIntercomDeviceEntity, BasePikIntercomIotIntercomRelayEntity, \
    BasePikIntercomEntity
from custom_components.pik_intercom.api import PikIntercomAPI
from custom_components.pik_intercom.const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistantType, config_entry, async_add_entities) -> bool:
    """Add a Pik Domofon IP intercom from a config entry."""

    config_entry_id = config_entry.entry_id

    _LOGGER.debug(f"[{config_entry_id}] Настройка платформы 'switch'")

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    new_entities: List[BasePikIntercomEntity] = [
        PikIntercomUnlockerSwitch(hass, config_entry_id, intercom_device)
        for intercom_device in api.devices.values()
    ]

    new_entities += [
        PikIntercomIotRelayUnlockerSwitch(hass, config_entry_id, iot_relay)
        for iot_relay in api.iot_relays.values()
    ]

    async_add_entities(new_entities, True)

    _LOGGER.debug(f"[{config_entry_id}] Завершение инициализации платформы 'switch'")

    return True


class _BaseUnlockerSwitch(SwitchEntity, ABC):
    @property
    @abstractmethod
    def _internal_object_identifier(self) -> Hashable:
        raise NotImplementedError

    def __init__(self) -> None:
        super().__init__()

        self.entity_id = f"switch.{self._internal_object_identifier}_unlocker"
        self._turn_off_waiter = None

    @property
    def icon(self) -> str:
        if self.is_on:
            return "mdi:door-closed"
        return "mdi:door-closed-lock"

    @property
    def unique_id(self) -> str:
        return f"intercom_unlocker_{self._internal_object_identifier}"

    @property
    def is_on(self) -> bool:
        return self._turn_off_waiter is not None

    def turn_on(self, **kwargs: Any) -> None:
        return asyncio.run_coroutine_threadsafe(
            self.async_turn_on(**kwargs),
            self.hass.loop,
        ).result()

    def turn_off(self, **kwargs: Any) -> None:
        return asyncio.run_coroutine_threadsafe(
            self.async_turn_on(**kwargs),
            self.hass.loop,
        ).result()

    @abstractmethod
    async def async_request_unlock(self) -> None:
        raise NotImplementedError

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on:
            return

        await self.async_request_unlock()

        hass = self.hass
        entity_id = self.entity_id

        async def _reset_lock(*_):
            await hass.services.async_call(
                "switch",
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: entity_id},
            )
            self._turn_off_waiter = None

        self._turn_off_waiter = async_call_later(
            self.hass,
            5,
            _reset_lock,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._turn_off_waiter = None


class PikIntercomIotRelayUnlockerSwitch(BasePikIntercomIotIntercomRelayEntity, _BaseUnlockerSwitch):
    def __init__(self, *args, **kwargs) -> None:
        BasePikIntercomIotIntercomRelayEntity.__init__(self, *args, **kwargs)
        _BaseUnlockerSwitch.__init__(self)

    @property
    def _internal_object_identifier(self) -> Hashable:
        return self._iot_relay.id

    @property
    def unique_id(self) -> str:
        return super().unique_id + "_iot_relay"

    @property
    def name(self) -> str:
        return self._iot_relay.friendly_name + " Открытие (IoT)"

    async def async_request_unlock(self) -> None:
        await self._iot_relay.async_unlock()


class PikIntercomUnlockerSwitch(BasePikIntercomDeviceEntity, _BaseUnlockerSwitch):
    def __init__(self, *args, **kwargs) -> None:
        BasePikIntercomDeviceEntity.__init__(self, *args, **kwargs)
        _BaseUnlockerSwitch.__init__(self)

    @property
    def _internal_object_identifier(self) -> Hashable:
        return self._intercom_device.id

    @property
    def name(self) -> Optional[str]:
        intercom_device = self._intercom_device
        return (
                       intercom_device.renamed_name or intercom_device.human_name or intercom_device.name
               ) + " Открытие"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        intercom_device = self._intercom_device
        return {
            "id": intercom_device.id,
            "scheme_id": intercom_device.scheme_id,
            "building_id": intercom_device.building_id,
            "property_id": intercom_device.property_id,
            "device_category": intercom_device.device_category,
            "kind": intercom_device.kind,
            "mode": intercom_device.mode,
            "name": intercom_device.name,
            "human_name": intercom_device.human_name,
            "renamed_name": intercom_device.renamed_name,
            "relays": intercom_device.relays,
            "checkpoint_relay_index": intercom_device.checkpoint_relay_index,
            "entrance": intercom_device.entrance,
            # "sip_account": intercom_device.sip_account,
            # "can_address": intercom_device.can_address,
        }

    async def async_request_unlock(self) -> None:
        await self._intercom_device.async_unlock()
