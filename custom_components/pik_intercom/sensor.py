"""Pik Intercom sensors."""

__all__ = ("async_setup_entry", "PikIntercomLastCallSessionSensor")

import logging
from typing import Any, Callable, Mapping, Optional

from homeassistant.const import DEVICE_CLASS_TIMESTAMP
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.const import DOMAIN, UPDATE_CONFIG_KEY_CALL_SESSIONS
from custom_components.pik_intercom.api import PikIntercomAPI
from custom_components.pik_intercom._base import BasePikIntercomEntity

_LOGGER = logging.getLogger(__name__)


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    config_entry_id = config_entry.entry_id

    _LOGGER.debug(f"Setting up 'sensor' platform for entry {config_entry_id}")

    api_object: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    await api_object.async_update_call_sessions(1)

    async_add_entities(
        [
            PikIntercomLastCallSessionSensor(config_entry_id),
        ],
        False,
    )

    return True


class PikIntercomLastCallSessionSensor(BasePikIntercomEntity):
    async def async_update_internal(self) -> None:
        await self.api_object.async_update_call_sessions(1)

    def __init__(self, config_entry_id: str) -> None:
        """Initialize the Pik Domofon intercom video stream."""
        super().__init__(config_entry_id)

        self.entity_id = f"sensor.last_call_session"
        self._entity_updater: Optional[Callable] = None

    @property
    def update_identifier(self) -> str:
        return self._config_entry_id

    @property
    def update_config_key(self) -> str:
        return UPDATE_CONFIG_KEY_CALL_SESSIONS

    @property
    def state(self) -> Optional[str]:
        last_call_session = self.api_object.last_call_session

        if last_call_session is None:
            return None

        return last_call_session.updated_at.isoformat()

    @property
    def available(self) -> bool:
        return self.api_object.last_call_session is not None

    @property
    def icon(self) -> str:
        return "mdi:phone"

    @property
    def name(self) -> str:
        return "Last Call Session"

    @property
    def device_state_attributes(self) -> Optional[Mapping[str, Any]]:
        last_call_session = self.api_object.last_call_session

        if last_call_session is None:
            return None

        return {
            "id": last_call_session.id,
            "property_id": last_call_session.property_id,
            "intercom_id": last_call_session.intercom_id,
            "call_number": last_call_session.call_number,
            "intercom_name": last_call_session.intercom_name,
            "photo_url": last_call_session.full_photo_url,
            "answered_customer_device_ids": list(
                last_call_session.answered_customer_device_ids
            ),
            "hangup": last_call_session.hangup,
            "created_at": last_call_session.created_at.isoformat(),
            "notified_at": (
                last_call_session.notified_at.isoformat()
                if last_call_session.notified_at
                else None
            ),
            "finished_at": (
                last_call_session.finished_at.isoformat()
                if last_call_session.finished_at
                else None
            ),
        }

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_TIMESTAMP
