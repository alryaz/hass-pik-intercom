"""Pik Intercom sensors."""

__all__ = (
    "async_setup_entry",
    "PikIntercomMeterTotalSensor",
    "PikIntercomMeterMonthSensor",
)

import logging
from dataclasses import dataclass
from functools import partial
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
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIntercomIotMeterEntity,
    PikIntercomIotMetersUpdateCoordinator,
    BasePikIntercomLastCallSessionEntity,
    PikIntercomLastCallSessionUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)


@callback
def _async_add_new_meter_entities(
    coordinator: PikIntercomIotMetersUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = coordinator.get_entities_dict(PikIntercomMeterSensor)

    new_entities = []
    for meter_id, meter in coordinator.api_object.iot_meters.items():
        for e in METER_ENTITY_DESCRIPTIONS:
            if (key := (meter_id, e.key)) not in entities:
                entities[key] = entity = PikIntercomMeterSensor(
                    coordinator, device=meter, entity_description=e
                )
                new_entities.append(entity)

    if new_entities:
        _LOGGER.debug(
            f"[{coordinator.config_entry.entry_id}] Adding {len(new_entities)} new sensor entities"
        )
        async_add_entities(new_entities)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom sensors based on a config entry."""

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikIntercomIotMetersUpdateCoordinator):
            # Run first time
            _async_add_new_meter_entities(coordinator, async_add_entities)

            # Add listener for future updates
            coordinator.async_add_listener(
                partial(
                    _async_add_new_meter_entities,
                    coordinator,
                    async_add_entities,
                )
            )
        elif isinstance(
            coordinator, PikIntercomLastCallSessionUpdateCoordinator
        ):
            async_add_entities(
                PikIntercomLastCallSessionTimestampSensor(
                    coordinator,
                    device=coordinator.data,
                    entity_description=entity_description,
                )
                for entity_description in LAST_CALL_SESSION_TIMESTAMPS
            )

    return True


@dataclass
class SourceSensorEntityDescription(SensorEntityDescription):
    source: str = None
    has_entity_name: bool = True


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


class PikIntercomMeterSensor(BasePikIntercomIotMeterEntity, SensorEntity):
    _attr_suggested_display_precision = 3

    entity_description: SourceSensorEntityDescription

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
        self._attr_native_value = getattr(
            self._internal_object, self.entity_description.source, None
        )


LAST_CALL_SESSION_TIMESTAMPS: Final = (
    SourceSensorEntityDescription(
        key="created_at",
        name="Created At",
        source="created_at",
        translation_key="last_call_session_created_at",
    ),
    SourceSensorEntityDescription(
        key="picked_up_at",
        name="Picked Up At",
        source="pickedup_at",
        translation_key="last_call_session_picked_up_at",
    ),
    SourceSensorEntityDescription(
        key="finished_at",
        name="Finished At",
        source="finished_at",
        translation_key="last_call_session_finished_at",
    ),
)


class PikIntercomLastCallSessionTimestampSensor(
    BasePikIntercomLastCallSessionEntity, SensorEntity
):
    entity_description: SourceSensorEntityDescription

    def _update_attr(self) -> None:
        super()._update_attr()
        if not (o := self._internal_object):
            self._attr_native_value = getattr(
                o, self.entity_description.source, None
            )
            self._attr_available = self._attr_native_value is not None
        else:
            self._attr_available = False
