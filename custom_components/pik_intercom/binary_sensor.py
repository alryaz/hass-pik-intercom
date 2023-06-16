from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIntercomLastCallSessionEntity,
    PikIntercomLastCallSessionUpdateCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikIntercomLastCallSessionUpdateCoordinator):
            async_add_entities([PikIntercomLastCallSessionSensor(coordinator, device=coordinator.data)])

    return True


class PikIntercomLastCallSessionSensor(BasePikIntercomLastCallSessionEntity, BinarySensorEntity):
    # _attr_icon = "mdi:phone"
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_name = "Active"
    _attr_translation_key = "last_call_session_active"
    _attr_icon = "mdi:phone-hangup"

    def _update_attr(self) -> None:
        super()._update_attr()

        if not (call_session := self._internal_object):
            self._attr_is_on = False
            return

        self._attr_is_on = call_session.notified_at and not call_session.finished_at
        self._attr_icon = (
            ("mdi:phone-in-talk" if call_session.pickedup_at else "mdi:phone-ring")
            if self._attr_is_on
            else "mdi:phone-hangup"
        )
        self._attr_extra_state_attributes.update(
            {
                "property_id": call_session.property_id,
                "property_name": call_session.property_name,
                "intercom_id": call_session.intercom_id,
                "intercom_name": call_session.intercom_name,
                "snapshot_url": call_session.snapshot_url,
            }
        )
