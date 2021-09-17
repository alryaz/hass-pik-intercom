"""Pik Intercom sensors."""

__all__ = ("async_setup_entry", "PikIntercomLastCallSessionSensor")

import logging
from typing import Any, Callable, Mapping, Optional

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.const import DATA_FINAL_CONFIG
from custom_components.pik_intercom._base import BasePikIntercomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    async_add_entities(
        [
            PikIntercomLastCallSessionSensor(config_entry.entry_id),
        ],
        True,
    )

    return True


class PikIntercomLastCallSessionSensor(BasePikIntercomEntity):
    def __init__(self, config_entry_id: str) -> None:
        """Initialize the Pik Domofon intercom video stream."""
        super().__init__(config_entry_id)

        self.entity_id = f"sensor.last_call_session"
        self._entity_updater: Optional[Callable] = None

    @property
    def state(self) -> Optional[str]:
        last_call_session = self.api_object.last_call_session

        if last_call_session is None:
            return None

        return last_call_session.updated_at.isoformat()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        time_interval = self.hass.data[DATA_FINAL_CONFIG][self._config_entry_id][
            CONF_SCAN_INTERVAL
        ]["last_call_session"]

        _LOGGER.debug(
            f"Scheduling last_call_session entity updater "
            f"with {time_interval.total_seconds()} interval"
        )
        self._entity_updater = async_track_time_interval(
            self.hass,
            lambda *args: self.async_schedule_update_ha_state(True),
            time_interval,
        )

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()

        if self._entity_updater:
            _LOGGER.debug("Cancelling last_call_session entity updater")
            self._entity_updater()

    @property
    def available(self) -> bool:
        return self.api_object.last_call_session is not None

    @property
    def icon(self) -> str:
        return "mdi:phone"

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

    async def async_update(self) -> None:
        await self.api_object.async_update_call_sessions()
