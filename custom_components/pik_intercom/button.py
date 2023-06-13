"""Pik Intercom buttons."""

__all__ = (
    "async_setup_entry",
    "PikIntercomPropertyPropertyDeviceUnlockerButton",
    "PikIntercomIotRelayUnlockerButton",
)

import asyncio
import logging
from abc import abstractmethod, ABC
from functools import partial
from typing import Dict, Type, Mapping

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.api import PikObjectWithUnlocker
from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIntercomCoordinatorEntity,
    BasePikIntercomPropertyDeviceEntity,
    BasePikIntercomIotRelayEntity,
    PikIntercomIotIntercomsUpdateCoordinator,
    PikIntercomPropertyIntercomsUpdateCoordinator,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)


@callback
def async_process_intercoms_generic(
    entity_cls: Type["_BaseUnlockerButton"],
    objects_dict: Mapping[int, PikObjectWithUnlocker],
    coordinator: PikIntercomIotIntercomsUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_id = coordinator.config_entry.entry_id
    try:
        entities: Dict[int, "_BaseUnlockerButton"] = getattr(coordinator, "unlocker_button_entities")
    except AttributeError:
        setattr(coordinator, "unlocker_button_entities", entities := {})

    new_entities = []
    for item_id, item in objects_dict.items():
        if item_id not in entities:
            _LOGGER.debug(f"[{entry_id}] Adding unlocker for {item}")
            current_sensor = entity_cls(coordinator, device=item)
            entities[item_id] = current_sensor
            new_entities.append(current_sensor)

    if new_entities:
        _LOGGER.debug(f"[{entry_id}] Adding {len(new_entities)} new button entities")
        async_add_entities(new_entities)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom IP intercom from a config entry."""

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikIntercomIotIntercomsUpdateCoordinator):
            entity_cls = PikIntercomIotRelayUnlockerButton
            objects_dict = coordinator.api_object.iot_relays
        elif isinstance(coordinator, PikIntercomPropertyIntercomsUpdateCoordinator):
            entity_cls = PikIntercomPropertyPropertyDeviceUnlockerButton
            objects_dict = coordinator.api_object.devices
        else:
            continue

        # Run first time
        async_process_intercoms_generic(entity_cls, objects_dict, coordinator, async_add_entities)

        # Add listener for future updates
        coordinator.async_add_listener(
            partial(
                async_process_intercoms_generic,
                entity_cls,
                objects_dict,
                coordinator,
                async_add_entities,
            )
        )

    return True


class _BaseUnlockerButton(BasePikIntercomCoordinatorEntity, ButtonEntity, ABC):
    """Base class for unlocking Intercom relays"""

    _attr_icon = "mdi:door-closed-lock"
    _internal_object: PikObjectWithUnlocker

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        ButtonEntity.__init__(self)

    def press(self) -> None:
        return asyncio.run_coroutine_threadsafe(
            self.async_press(),
            self.hass.loop,
        ).result()

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_name += " Unlocker"

    async def async_press(self) -> None:
        await self._internal_object.async_unlock()


class PikIntercomPropertyPropertyDeviceUnlockerButton(BasePikIntercomPropertyDeviceEntity, _BaseUnlockerButton):
    """Property Intercom Unlocker Adapter"""

    UNIQUE_ID_FORMAT = BasePikIntercomPropertyDeviceEntity.UNIQUE_ID_FORMAT + "__unlocker"


class PikIntercomIotRelayUnlockerButton(BasePikIntercomIotRelayEntity, _BaseUnlockerButton):
    """IoT Relay Unlocker Adapter"""

    UNIQUE_ID_FORMAT = BasePikIntercomIotRelayEntity.UNIQUE_ID_FORMAT + "__unlocker"
