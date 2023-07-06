"""Pik Intercom sensors."""

__all__ = (
    "async_setup_entry",
    "PikIotMeterSensor",
    "PikLastCallSessionSensor",
)

import logging
from abc import ABC
from dataclasses import dataclass
from typing import Final

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.components.sensor.const import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
)
from homeassistant.helpers.restore_state import RestoreEntity

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIntercomIotMeterEntity,
    PikIotMetersUpdateCoordinator,
    BasePikLastCallSessionEntity,
    PikLastCallSessionUpdateCoordinator,
    BasePikIcmIntercomEntity,
    BasePikIntercomEntity,
    PikIcmPropertyUpdateCoordinator,
    PikIcmIntercomUpdateCoordinator,
)
from custom_components.pik_intercom.helpers import (
    async_add_entities_with_listener,
)

_LOGGER: Final = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        if isinstance(coordinator, PikIotMetersUpdateCoordinator):
            containers = coordinator.api_object.iot_meters
            entity_classes = PikIotMeterSensor
            entity_descriptions = METER_ENTITY_DESCRIPTIONS
        elif isinstance(
            coordinator,
            (PikIcmPropertyUpdateCoordinator, PikIcmIntercomUpdateCoordinator),
        ):
            containers = coordinator.api_object.iot_intercoms
            entity_classes = PikIcmIntercomSensor
            entity_descriptions = ICM_INTERCOM_ENTITY_DESCRIPTIONS
        else:
            if isinstance(coordinator, PikLastCallSessionUpdateCoordinator):
                async_add_entities(
                    PikLastCallSessionSensor(
                        coordinator,
                        device=coordinator.data,
                        entity_description=entity_description,
                    )
                    for entity_description in LAST_CALL_SESSION_TIMESTAMPS
                )
            continue

        # Create updater
        async_add_entities_with_listener(
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            containers=containers,
            entity_classes=entity_classes,
            entity_descriptions=entity_descriptions,
            logger=_LOGGER,
        )

    return True


@dataclass
class SourceSensorEntityDescription(SensorEntityDescription):
    source: str = None
    has_entity_name: bool = True
    unavailable_if_none: bool = False


METER_ENTITY_DESCRIPTIONS: Final = (
    SourceSensorEntityDescription(
        key="total",
        name="Current Indication",
        icon="mdi:counter",
        translation_key="meter_total",
        source="current_value_numeric",
        state_class=SensorStateClass.TOTAL,
    ),
    SourceSensorEntityDescription(
        key="month",
        name="Monthly Usage",
        icon="mdi:water-plus",
        translation_key="meter_month",
        source="month_value_numeric",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


class PikSensorEntity(BasePikIntercomEntity, SensorEntity, ABC):
    entity_description: SourceSensorEntityDescription

    def _update_attr(self) -> None:
        super()._update_attr()
        if o := self._internal_object:
            e = self.entity_description
            self._attr_native_value = getattr(o, e.source, None)
            self._attr_available = (
                self._attr_native_value is not None
                if e.unavailable_if_none
                else True
            )
        else:
            self._attr_available = False


ICM_INTERCOM_ENTITY_DESCRIPTIONS: Final = (
    SourceSensorEntityDescription(
        key="ip_address",
        name="IP Address",
        source="ip_address",
        translation_key="ip_address",
        icon="mdi:ip",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class PikIcmIntercomSensor(BasePikIcmIntercomEntity, PikSensorEntity):
    pass


class PikIotMeterSensor(
    BasePikIntercomIotMeterEntity, PikSensorEntity, RestoreEntity
):
    _attr_suggested_display_precision = 3

    def _update_attr(self) -> None:
        super()._update_attr()
        if self._internal_object.kind in ("cold", "hot"):
            self._attr_device_class = SensorDeviceClass.WATER
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        else:
            _LOGGER.warning(
                f"[{self}] New meter kind: '{self._internal_object.kind}. "
                f"Please, report this to the developer ASAP!"
            )


LAST_CALL_SESSION_TIMESTAMPS: Final = (
    SourceSensorEntityDescription(
        key="created_at",
        name="Created At",
        source="created_at",
        translation_key="last_call_session_created_at",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SourceSensorEntityDescription(
        key="picked_up_at",
        name="Picked Up At",
        source="pickedup_at",
        translation_key="last_call_session_picked_up_at",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SourceSensorEntityDescription(
        key="finished_at",
        name="Finished At",
        source="finished_at",
        translation_key="last_call_session_finished_at",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


class PikLastCallSessionSensor(BasePikLastCallSessionEntity, PikSensorEntity):
    pass
