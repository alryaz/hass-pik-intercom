"""Pik Intercom buttons."""

__all__ = (
    "async_setup_entry",
    "PikIntercomPropertyPropertyDeviceUnlockerButton",
    "PikIntercomIotRelayUnlockerButton",
)

import asyncio
import logging
from abc import abstractmethod, ABC

from homeassistant.components.button import ButtonEntity
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

    _LOGGER.debug(log_prefix + "Настройка платформы 'button'")

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    # Add Intercom Entities
    new_property_device_entities = [
        PikIntercomPropertyPropertyDeviceUnlockerButton(
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
        PikIntercomIotRelayUnlockerButton(hass, config_entry_id, iot_relay)
        for iot_relay in api.iot_relays.values()
    ]

    _LOGGER.debug(
        log_prefix + f"Будут добавлены {len(new_property_device_entities)} "
        f"IoT-объектов открытия"
    )

    async_add_entities(
        (*new_property_device_entities, *new_iot_relay_entities), True
    )

    _LOGGER.debug(log_prefix + "Завершение инициализации платформы 'button'")

    return True


class _BaseUnlockerButton(BasePikIntercomEntity, ButtonEntity, ABC):
    """Base class for unlocking Intercom relays"""

    _attr_icon: str = "mdi:door-closed-lock"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        ButtonEntity.__init__(self)

        self.entity_id = f"button.{self._internal_object_identifier.replace('__', '_')}_unlocker"

    @property
    def name(self) -> str:
        return self.base_name + " Открытие"

    @property
    def unique_id(self) -> str:
        return f"intercom_unlocker__{self._internal_object_identifier}"

    def press(self) -> None:
        return asyncio.run_coroutine_threadsafe(
            self.async_press(),
            self.hass.loop,
        ).result()

    @abstractmethod
    async def async_press(self) -> None:
        raise NotImplementedError


class PikIntercomPropertyPropertyDeviceUnlockerButton(
    _BaseUnlockerButton, BasePikIntercomPropertyDeviceEntity
):
    """Property Intercom Unlocker Adapter"""

    async def async_press(self) -> None:
        await self._intercom_device.async_unlock()


class PikIntercomIotRelayUnlockerButton(
    _BaseUnlockerButton, BasePikIntercomIotRelayEntity
):
    """IoT Relay Unlocker Adapter"""

    async def async_press(self) -> None:
        await self._iot_relay.async_unlock()
