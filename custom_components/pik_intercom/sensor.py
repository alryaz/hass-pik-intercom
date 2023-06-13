"""Pik Intercom sensors."""

__all__ = ("async_setup_entry", "PikIntercomLastCallSessionSensor")

import logging
from functools import partial
from typing import (
    Callable,
    Optional,
    Dict,
    TYPE_CHECKING,
)

from homeassistant.components.sensor import SensorEntity
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
    BasePikIntercomDeviceEntity,
    BasePikIntercomIotMeterEntity,
    PikIntercomIotMetersUpdateCoordinator,
)

if TYPE_CHECKING:
    from custom_components.pik_intercom.api import PikIntercomAPI

_LOGGER = logging.getLogger(__name__)


@callback
def async_add_new_meter_entities(
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

    # # Add single Pik Intercom
    # async_add_entities(
    #     [
    #         PikIntercomLastCallSessionSensor(hass, entry.entry_id),
    #     ],
    #     True,
    # )

    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(coordinator, PikIntercomIotMetersUpdateCoordinator):
            # Run first time
            async_add_new_meter_entities(coordinator, async_add_entities)

            # Add listener for future updates
            coordinator.async_add_listener(
                partial(
                    async_add_new_meter_entities,
                    coordinator,
                    async_add_entities,
                )
            )

    return True


class PikIntercomLastCallSessionSensor(BasePikIntercomDeviceEntity, SensorEntity):
    _attr_name = "Last Call Session"
    _attr_icon = "mdi:phone"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = True

    def __init__(self, *args, api_object: "PikIntercomAPI", **kwargs) -> None:
        """Initialize the Pik Intercom intercom video stream."""
        super().__init__(*args, **kwargs)

        self._api_object = api_object
        self.entity_id = "sensor.last_call_session"
        self._entity_updater: Optional[Callable] = None

    @property
    def api_object(self) -> "PikIntercomAPI":
        return self._api_object

    @property
    def _common_device_identifier(self) -> str:
        return f"last_call_session__{self.api_object.username}"

    async def async_update(self) -> None:
        await self.api_object.async_update_call_sessions(1)

        new_value = None
        if last_call_session := self.api_object.last_call_session:
            self._attr_extra_state_attributes = {
                "id": last_call_session.id,
                "property_id": last_call_session.property_id,
                "property_name": last_call_session.property_name,
                "intercom_id": last_call_session.intercom_id,
                "intercom_name": last_call_session.intercom_name,
                "photo_url": last_call_session.full_photo_url,
                "finished_at": (last_call_session.finished_at.isoformat() if last_call_session.finished_at else None),
                "pickedup_at": (last_call_session.pickedup_at.isoformat() if last_call_session.pickedup_at else None),
            }

            if last_call_session.notified_at:
                new_value = last_call_session.notified_at.isoformat()

        self._attr_available = new_value is not None
        self._attr_native_value = new_value


class _BasePikIntercomMeterSensor(BasePikIntercomIotMeterEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_suggested_display_precision = 3


class PikIntercomMeterTotalSensor(_BasePikIntercomMeterSensor):
    _attr_icon = "mdi:counter"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_unique_id = f"iot_meter__{self._internal_object.id}__total"
        self._attr_name = f"{self._common_device_name} Current"
        self._attr_native_value = self._internal_object.current_value_numeric


class PikIntercomMeterMonthSensor(_BasePikIntercomMeterSensor):
    _attr_icon = "mdi:water-plus"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_unique_id = f"iot_meter__{self._internal_object.id}__month"
        self._attr_name = f"{self._common_device_name} Month"
        self._attr_native_value = self._internal_object.month_value_numeric
