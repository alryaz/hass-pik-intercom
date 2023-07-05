from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
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
        if isinstance(
            coordinator, PikIntercomLastCallSessionUpdateCoordinator
        ):
            async_add_entities(
                [
                    PikIntercomLastCallSessionActiveSensor(
                        coordinator, device=coordinator.data
                    )
                ]
            )

    return True


class PikIntercomLastCallSessionActiveSensor(
    BasePikIntercomLastCallSessionEntity, BinarySensorEntity
):
    entity_description = BinarySensorEntityDescription(
        key="active",
        name="Active",
        icon="mdi:phone-hangup",
        device_class=BinarySensorDeviceClass.SOUND,
        translation_key="last_call_session_active",
        has_entity_name=True,
    )

    def _update_attr(self) -> None:
        super()._update_attr()

        # Previously set, and reset
        self._attr_available = True

        if not (call_session := self._internal_object):
            self._attr_is_on = False
            return

        self._attr_is_on = (
            call_session.notified_at and not call_session.finished_at
        )
        self._attr_icon = (
            (
                "mdi:phone-in-talk"
                if call_session.pickedup_at
                else "mdi:phone-ring"
            )
            if self._attr_is_on
            else self.entity_description.icon
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
