"""Pik Intercom sensors."""

__all__ = ("async_setup_entry", "PikIntercomLastCallSessionSensor")

import logging
from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
)

from homeassistant.const import DEVICE_CLASS_TIMESTAMP
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom._base import BasePikIntercomEntity
from custom_components.pik_intercom.const import (
    CONF_CALL_SESSIONS_UPDATE_INTERVAL,
    DATA_FINAL_CONFIG,
    UPDATE_CONFIG_KEY_CALL_SESSIONS,
)

_LOGGER = logging.getLogger(__name__)


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    config_entry_id = config_entry.entry_id

    _LOGGER.debug(f"[{config_entry_id}] Настройка платформы 'sensor'")

    async_add_entities(
        [
            PikIntercomLastCallSessionSensor(hass, config_entry_id),
        ],
        True,
    )

    _LOGGER.debug(
        f"[{config_entry_id}] Завершение инициализации платформы 'sensor'"
    )

    return True


class PikIntercomLastCallSessionSensor(BasePikIntercomEntity):
    def __init__(self, *args, **kwargs) -> None:
        """Initialize the Pik Intercom intercom video stream."""
        super().__init__(*args, **kwargs)

        self.entity_id = "sensor.last_call_session"
        self._entity_updater: Optional[Callable] = None

    @property
    def _internal_object_identifier(self) -> str:
        return f"last_call_session__{self.api_object.username}"

    @property
    def base_name(self) -> str:
        return "Last Call Session"

    async def async_self_update(self) -> None:
        await self.api_object.async_update_call_sessions(1)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        hass = self.hass
        config_entry_id = self._config_entry_id
        interval = hass.data[DATA_FINAL_CONFIG][config_entry_id][
            CONF_CALL_SESSIONS_UPDATE_INTERVAL
        ]

        _LOGGER.debug(
            f"[{config_entry_id}] Scheduling {self.entity_id} updates "
            f"with {interval.total_seconds()} seconds interval"
        )
        self._entity_updater = async_track_time_interval(
            hass,
            lambda *_: self.async_schedule_update_ha_state(True),
            interval,
        )

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()

        if self._entity_updater:
            _LOGGER.debug(
                f"[{self._config_entry_id}] Cancelling {self.entity_id} scheduled updates"
            )
            self._entity_updater()

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
    def extra_state_attributes(self) -> Optional[Mapping[str, Any]]:
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
