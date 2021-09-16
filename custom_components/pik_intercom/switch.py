"""Pik Intercom switches."""

__all__ = ("async_setup_entry", "PikIntercomUnlockerSwitch")

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom._base import BasePikIntercomEntity
from custom_components.pik_intercom.api import PikIntercomDevice, PikIntercomAPI

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Domofon IP intercom from a config entry."""

    config_entry_id = config_entry.entry_id

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    async_add_entities(
        [
            PikIntercomUnlockerSwitch(config_entry_id, intercom_device)
            for intercom_device in api.devices.values()
        ]
    )

    return True


class PikIntercomUnlockerSwitch(BasePikIntercomEntity, SwitchEntity):
    def __init__(
        self, config_entry_id: str, intercom_device: PikIntercomDevice
    ) -> None:
        BasePikIntercomEntity.__init__(self, config_entry_id)
        SwitchEntity.__init__(self)

        self.entity_id = f"switch.{intercom_device.id}_unlocker"

        self._intercom_device = intercom_device
        self._turn_off_waiter = None

    @property
    def icon(self) -> str:
        if self.is_on:
            return "mdi:door-closed"
        return "mdi:door-closed-lock"

    @property
    def name(self) -> Optional[str]:
        intercom_device = self._intercom_device
        return (
            intercom_device.renamed_name
            or intercom_device.human_name
            or intercom_device.name
        ) + " Открытие"

    @property
    def unique_id(self) -> Optional[str]:
        intercom_device = self._intercom_device
        return f"intercom_unlock_{intercom_device.property_id}_{intercom_device.id}"

    @property
    def is_on(self) -> bool:
        return self._turn_off_waiter is not None

    @property
    def device_state_attributes(self) -> Mapping[str, Any]:
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
            "face_detection": intercom_device.face_detection,
        }

    @property
    def device_info(self) -> Dict[str, Any]:
        intercom_device = self._intercom_device
        return {
            "name": intercom_device.name,
            "manufacturer": intercom_device.device_category,
            "model": intercom_device.kind + " / " + intercom_device.mode,
            "identifiers": {(DOMAIN, intercom_device.id)},
        }

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on:
            return

        await self._intercom_device.async_unlock()

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