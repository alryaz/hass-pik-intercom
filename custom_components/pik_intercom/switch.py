import asyncio
import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom import DATA_ENTITIES, DOMAIN, PikDomofonAPI
from custom_components.pik_intercom.api import PikDomofonIntercom

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Domofon IP intercom from a config entry."""

    api: PikDomofonAPI = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        [
            PikDomofonUnlocker(intercom_object)
            for intercom_object in api.intercoms.values()
        ]
    )

    return True


class PikDomofonUnlocker(SwitchEntity):
    def __init__(self, intercom_object: PikDomofonIntercom) -> None:
        super().__init__()

        self.entity_id = f"switch.{intercom_object.id}_unlocker"

        self._intercom_object = intercom_object
        self._turn_off_waiter = None

    @property
    def icon(self) -> str:
        if self.is_on:
            return "mdi:door-closed"
        return "mdi:door-closed-lock"

    async def async_added_to_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].setdefault(
            self.registry_entry.config_entry_id, []
        ).append(self)

    async def async_will_remove_from_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].get(
            self.registry_entry.config_entry_id, []
        ).remove(self)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def name(self) -> Optional[str]:
        intercom_object = self._intercom_object
        return (
            intercom_object.renamed_name
            or intercom_object.human_name
            or intercom_object.name
        ) + " Открытие"

    @property
    def unique_id(self) -> Optional[str]:
        intercom_object = self._intercom_object
        return f"intercom_unlock_{intercom_object.property_id}_{intercom_object.id}"

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

    @property
    def is_on(self) -> bool:
        return self._turn_off_waiter is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on:
            return

        await self._intercom_object.async_unlock()

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
