"""Pik Intercom switches."""

__all__ = (
    "async_setup_entry",
    "PikIntercomPropertyPropertyDeviceUnlockerSwitch",
    "PikIntercomIotRelayUnlockerSwitch",
)

import asyncio
import logging
from abc import abstractmethod, ABC
from typing import Any, Mapping, Hashable

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom._base import (
    BasePikIntercomPropertyDeviceEntity,
    BasePikIntercomIotRelayEntity,
    BasePikIntercomEntity,
)
from custom_components.pik_intercom.api import PikIntercomAPI
from custom_components.pik_intercom.const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Intercom IP intercom from a config entry."""

    config_entry_id = config_entry.entry_id

    log_prefix = f"[{config_entry_id}] "

    _LOGGER.debug(log_prefix + "Настройка платформы 'switch'")

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    # Add Intercom Entities
    new_property_device_entities = [
        PikIntercomPropertyPropertyDeviceUnlockerSwitch(
            hass, config_entry_id, intercom_device
        )
        for intercom_device in api.devices.values()
    ]

    _LOGGER.debug(
        log_prefix + f"Будут добавлены {len(new_property_device_entities)} "
        f"объектов открытия по владениям"
    )

    # Add IoT Relays
    new_iot_relay_entities = [
        PikIntercomIotRelayUnlockerSwitch(hass, config_entry_id, iot_relay)
        for iot_relay in api.iot_relays.values()
    ]

    _LOGGER.debug(
        log_prefix + f"Будут добавлены {len(new_property_device_entities)} "
        f"IoT-объектов открытия"
    )

    async_add_entities(
        (*new_property_device_entities, *new_iot_relay_entities), True
    )

    _LOGGER.debug(log_prefix + "Завершение инициализации платформы 'switch'")

    return True


class _BaseUnlockerSwitch(BasePikIntercomEntity, SwitchEntity, ABC):
    """Base class for unlocking switches"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        SwitchEntity.__init__(self)

        self.entity_id = f"switch.{self._internal_object_identifier}_unlocker"
        self._turn_off_waiter = None

    @property
    def icon(self) -> str:
        if self.is_on:
            return "mdi:door-closed"
        return "mdi:door-closed-lock"

    @property
    def is_on(self) -> bool:
        return self._turn_off_waiter is not None

    @property
    def name(self) -> str:
        return self.base_name + " Открытие"

    @property
    def unique_id(self) -> str:
        return f"intercom_unlocker__{self._internal_object_identifier}"

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


class PikIntercomPropertyPropertyDeviceUnlockerSwitch(
    _BaseUnlockerSwitch, BasePikIntercomPropertyDeviceEntity
):
    async def async_request_unlock(self) -> None:
        await self._intercom_device.async_unlock()


class PikIntercomIotRelayUnlockerSwitch(
    _BaseUnlockerSwitch, BasePikIntercomIotRelayEntity
):
    """IoT Relay Unlocker Adapter"""

    async def async_request_unlock(self) -> None:
        await self._iot_relay.async_unlock()
