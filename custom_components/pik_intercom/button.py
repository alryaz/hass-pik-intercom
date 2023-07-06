"""Pik Intercom buttons."""

__all__ = (
    "async_setup_entry",
    "PikIcmIntercomUnlockerButton",
    "PikIntercomIotRelayUnlockerButton",
)

import asyncio
import logging
from abc import ABC

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIcmIntercomEntity,
    BasePikIotRelayEntity,
    PikIotIntercomsUpdateCoordinator,
    PikIcmIntercomUpdateCoordinator,
    BasePikEntity,
    BasePikLastCallSessionEntity,
    PikLastCallSessionUpdateCoordinator,
    PikIcmPropertyUpdateCoordinator,
    async_add_entities_with_listener,
)
from custom_components.pik_intercom.helpers import (
    get_logger,
)
from pik_intercom import ObjectWithUnlocker

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom IP intercom from a config entry."""
    logger = get_logger(_LOGGER)

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikIotIntercomsUpdateCoordinator):
            objects_dict = coordinator.api_object.iot_relays
            entity_cls = PikIntercomIotRelayUnlockerButton
        elif isinstance(
            coordinator,
            (PikIcmIntercomUpdateCoordinator, PikIcmPropertyUpdateCoordinator),
        ):
            objects_dict = coordinator.api_object.icm_intercoms
            entity_cls = PikIcmIntercomUnlockerButton
        else:
            if isinstance(coordinator, PikLastCallSessionUpdateCoordinator):
                async_add_entities(
                    [
                        PikCallSessionUnlockerButton(
                            coordinator, device=coordinator.data
                        )
                    ]
                )
            continue

        # Run first time
        async_add_entities_with_listener(
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            containers=objects_dict,
            entity_classes=entity_cls,
            logger=logger,
        )

    return True


class _BaseUnlockerButton(BasePikEntity, ButtonEntity, ABC):
    """Base class for unlocking Intercom relays"""

    _internal_object: ObjectWithUnlocker

    entity_description = ButtonEntityDescription(
        key="unlocker",
        name="Unlocker",
        icon="mdi:door-closed-lock",
        translation_key="unlocker",
        has_entity_name=True,
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        ButtonEntity.__init__(self)

    def press(self) -> None:
        return asyncio.run_coroutine_threadsafe(
            self.async_press(),
            self.hass.loop,
        ).result()

    async def async_press(self) -> None:
        self.logger.debug(f"Will unlock {self._internal_object}")
        await self._internal_object.unlock()


class PikIcmIntercomUnlockerButton(
    BasePikIcmIntercomEntity, _BaseUnlockerButton
):
    """Property Intercom Unlocker Adapter"""


class PikIntercomIotRelayUnlockerButton(
    BasePikIotRelayEntity, _BaseUnlockerButton
):
    """IoT Relay Unlocker Adapter"""


class PikCallSessionUnlockerButton(
    BasePikLastCallSessionEntity, _BaseUnlockerButton
):
    """Last call session unlock delegator."""

    def _update_attr(self) -> None:
        super()._update_attr()
        if not (call_session := self._internal_object):
            return
        self._attr_extra_state_attributes["target_relay_ids"] = (
            list(call_session.target_relay_ids)
            if hasattr(call_session, "target_relay_ids")
            else None
        )
