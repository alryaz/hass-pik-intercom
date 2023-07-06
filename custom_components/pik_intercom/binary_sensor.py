from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.const import *
from custom_components.pik_intercom.entity import (
    BasePikLastCallSessionEntity,
    PikLastCallSessionUpdateCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikLastCallSessionUpdateCoordinator):
            async_add_entities(
                [
                    PikLastCallSessionActiveSensor(
                        coordinator, device=coordinator.data
                    )
                ]
            )

    return True


class PikLastCallSessionActiveSensor(
    BasePikLastCallSessionEntity, BinarySensorEntity
):
    call_session_attributes: Final = (
        ATTR_CALL_DURATION,
        ATTR_CALL_FROM,
        ATTR_CALL_ID,
        ATTR_GEO_UNIT_ID,
        ATTR_GEO_UNIT_SHORT_NAME,
        ATTR_HANGUP,
        ATTR_IDENTIFIER,
        ATTR_INTERCOM_ID,
        ATTR_INTERCOM_NAME,
        ATTR_MODE,
        ATTR_PROPERTY_ID,
        ATTR_PROPERTY_NAME,
        ATTR_PROVIDER,
        ATTR_PROXY,
        ATTR_SESSION_ID,
        ATTR_SIP_PROXY,
        ATTR_SNAPSHOT_URL,
        ATTR_TARGET_RELAY_IDS,
    )
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

        # populate call session data
        attrs = self._attr_extra_state_attributes
        for attribute in self.call_session_attributes:
            attrs[attribute] = getattr(call_session, attribute, None)
