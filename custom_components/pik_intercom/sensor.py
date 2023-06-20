"""Pik Intercom sensors."""

__all__ = ("async_setup_entry", "PikIntercomMeterTotalSensor", "PikIntercomMeterMonthSensor")

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from functools import partial
from typing import Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
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
    entry_id = coordinator.config_entry.entry_id
    try:
        entities_current: Dict[int, PikIntercomMeterMonthSensor] = getattr(coordinator, "entities_current")
    except AttributeError:
        setattr(coordinator, "entities_current", entities_current := {})

    try:
        entities_month: Dict[int, PikIntercomMeterTotalSensor] = getattr(coordinator, "entities_month")
    except AttributeError:
        setattr(coordinator, "entities_month", entities_month := {})

    new_entities = []
    for meter_id, meter in coordinator.api_object.iot_meters.items():
        if meter_id not in entities_current:
            _LOGGER.debug(f"[{entry_id}] Adding current meter value sensor for {meter.id}")
            current_sensor = PikIntercomMeterMonthSensor(coordinator, device=meter)
            entities_current[meter_id] = current_sensor
            new_entities.append(current_sensor)
        if meter_id not in entities_month:
            _LOGGER.debug(f"[{entry_id}] Adding month meter value sensor for {meter.id}")
            month_sensor = PikIntercomMeterTotalSensor(coordinator, device=meter)
            entities_month[meter_id] = month_sensor
            new_entities.append(month_sensor)

    if new_entities:
        _LOGGER.debug(f"[{entry_id}] Adding {len(new_entities)} new sensor entities")
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
        elif isinstance(coordinator, PikIntercomLastCallSessionUpdateCoordinator):
            async_add_entities(
                entity_cls(coordinator, device=coordinator.data)
                for entity_cls in (
                    PikIntercomLastCallSessionCreatedAtSensor,
                    PikIntercomLastCallSessionFinishedAtSensor,
                    PikIntercomLastCallSessionPickedUpAtSensor,
                )
            )

    return True


class _BasePikIntercomMeterSensor(BasePikIntercomIotMeterEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _attr_translation_key = "meter"

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


class PikIntercomMeterTotalSensor(_BasePikIntercomMeterSensor):
    UNIQUE_ID_FORMAT = "iot_meter__{}__total"

    _attr_name = "Current Indication"
    _attr_icon = "mdi:counter"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_native_value = self._internal_object.current_value_numeric


class PikIntercomMeterMonthSensor(_BasePikIntercomMeterSensor):
    UNIQUE_ID_FORMAT = "iot_meter__{}__month"

    _attr_name = "Monthly Usage"
    _attr_icon = "mdi:water-plus"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_native_value = self._internal_object.month_value_numeric


class _BasePikIntercomLastCallSessionTimestampSensor(BasePikIntercomLastCallSessionEntity, SensorEntity, ABC):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "timestamp"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_name = self.__class__._attr_name
        if self._internal_object:
            self._attr_native_value = (timestamp := self.timestamp)
            self._attr_available = timestamp is not None
        else:
            self._attr_available = False

    @property
    @abstractmethod
    def timestamp(self) -> Optional[datetime]:
        raise NotImplementedError


class PikIntercomLastCallSessionCreatedAtSensor(_BasePikIntercomLastCallSessionTimestampSensor):
    UNIQUE_ID_FORMAT = f"{_BasePikIntercomLastCallSessionTimestampSensor.UNIQUE_ID_FORMAT}__created_at"

    _attr_name = "Created At"
    _attr_translation_key = "created_at"

    @property
    def timestamp(self) -> Optional[datetime]:
        return self._internal_object.created_at


class PikIntercomLastCallSessionPickedUpAtSensor(_BasePikIntercomLastCallSessionTimestampSensor):
    UNIQUE_ID_FORMAT = f"{_BasePikIntercomLastCallSessionTimestampSensor.UNIQUE_ID_FORMAT}__picked_up_at"

    _attr_name = "Picked Up At"
    _attr_translation_key = "picked_up_at"

    @property
    def timestamp(self) -> Optional[datetime]:
        return self._internal_object.pickedup_at


class PikIntercomLastCallSessionFinishedAtSensor(_BasePikIntercomLastCallSessionTimestampSensor):
    UNIQUE_ID_FORMAT = f"{_BasePikIntercomLastCallSessionTimestampSensor.UNIQUE_ID_FORMAT}__finished_at"

    _attr_name = "Finished At"

    _timestamp_name_suffix = "Finished At"
    _attr_translation_key = "finished_at"

    @property
    def timestamp(self) -> Optional[datetime]:
        return self._internal_object.finished_at
