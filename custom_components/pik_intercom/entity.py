import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import (
    TypeVar,
    Any,
    TYPE_CHECKING,
    Generic,
    Optional,
    ClassVar,
)

from homeassistant.const import ATTR_ID, ATTR_LOCATION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity, )

from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikPropertyDevice,
    PikIotIntercom,
    PikIotRelay,
    PikIotMeter,
    PikIotCamera,
    PikActiveCallSession,
)
from custom_components.pik_intercom.const import DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    # noinspection PyUnresolvedReferences
    from custom_components.pik_intercom.api import _BaseObject

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class BasePikIntercomUpdateCoordinator(DataUpdateCoordinator[_T], ABC, Generic[_T]):
    """Base class for update coordinators used by Pik Intercom integration"""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api_object: "PikIntercomAPI",
        update_interval: Optional[timedelta] = None,
        retries: int = 3,
    ) -> None:
        """Initialize Pik Intercom personal intercoms data updater."""
        self.api_object = api_object
        self.update_retries = retries

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    @abstractmethod
    async def _async_update_internal(self) -> _T:
        raise NotImplementedError

    async def _async_update_data(self) -> _T:
        """Fetch data."""
        for i in range(self.update_retries):
            try:
                return await self._async_update_internal()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if (i + 1) == self.update_retries:
                    msg = f"Unable to fetch data: {exc}"
                    raise UpdateFailed(msg) from exc
                else:
                    # Sleep for two seconds between requests
                    await asyncio.sleep(2)


class PikIntercomLastCallSessionUpdateCoordinator(BasePikIntercomUpdateCoordinator[PikActiveCallSession]):
    async def _async_update_internal(self) -> Optional[PikActiveCallSession]:
        """Fetch data."""
        _LOGGER.debug(f"[{self.config_entry.entry_id}] Performing last call session update")
        return await self.api_object.async_get_current_call_session()


class PikIntercomPropertyIntercomsUpdateCoordinator(BasePikIntercomUpdateCoordinator[None]):
    def __init__(
        self,
        *args,
        property_id: int,
        **kwargs,
    ) -> None:
        self.property_id = property_id
        super().__init__(*args, **kwargs)

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        _LOGGER.debug(f"[{self.config_entry.entry_id}] Performing property intercoms update")
        await self.api_object.async_update_property_intercoms(self.property_id)


class PikIntercomIotIntercomsUpdateCoordinator(BasePikIntercomUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        _LOGGER.debug(f"[{self.config_entry.entry_id}] Performing IoT intercoms update")
        await self.api_object.async_update_iot_intercoms()


class PikIntercomIotCamerasUpdateCoordinator(BasePikIntercomUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        _LOGGER.debug(f"[{self.config_entry.entry_id}] Performing IoT cameras update")
        await self.api_object.async_update_iot_cameras()


class PikIntercomIotMetersUpdateCoordinator(BasePikIntercomUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        _LOGGER.debug(f"[{self.config_entry.entry_id}] Performing IoT meters update")
        await self.api_object.async_update_iot_meters()


_TBasePikIntercomUpdateCoordinator = TypeVar(
    "_TBasePikIntercomUpdateCoordinator",
    bound=BasePikIntercomUpdateCoordinator,
)

_TBaseObject = TypeVar("_TBaseObject", bound="_BaseObject")


class BasePikIntercomEntity(
    CoordinatorEntity[_TBasePikIntercomUpdateCoordinator],
    ABC,
    Generic[_TBasePikIntercomUpdateCoordinator, _TBaseObject],
):
    UNIQUE_ID_FORMAT: ClassVar[Optional[str]] = None

    _attr_has_entity_name = True

    def __init__(self, *args, device: _TBaseObject, **kwargs) -> None:
        self._internal_object: _TBaseObject = device
        super().__init__(*args, **kwargs)
        self._update_unique_id()
        self._update_attr()

    @callback
    def _update_unique_id(self) -> None:
        if self.UNIQUE_ID_FORMAT:
            self._attr_unique_id = self.UNIQUE_ID_FORMAT.format(self._internal_object.id)

    @callback
    def _update_attr(self) -> None:
        """Update the state and attributes."""
        self._attr_extra_state_attributes = {}
        if (device := self._internal_object) is not None:
            self._attr_extra_state_attributes[ATTR_ID] = device.id
            if hasattr(device, "geo_unit_short_name"):
                self._attr_extra_state_attributes[ATTR_LOCATION] = device.geo_unit_short_name

        self._attr_device_info = DeviceInfo(
            name=self._common_device_name,
            identifiers={(DOMAIN, (device_identifier := self._common_device_identifier))},
            manufacturer=MANUFACTURER,
            # suggested_area=getattr(self._internal_object, "geo_unit_short_name", None),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attr()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Keep possibility of using _attr_available"""
        return super().available and self._attr_available

    @property
    def api_object(self) -> "PikIntercomAPI":
        return self.coordinator.api_object

    @property
    @abstractmethod
    def _common_device_identifier(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def _common_device_name(self) -> str:
        raise NotImplementedError


class BasePikIntercomPropertyDeviceEntity(
    BasePikIntercomEntity[PikIntercomPropertyIntercomsUpdateCoordinator, PikPropertyDevice]
):
    UNIQUE_ID_FORMAT = "property_intercom__{}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_device_info.update(
            manufacturer=device.device_category or MANUFACTURER,
            model=f"{device.kind or '-'} / {device.mode or '-'}",
        )
        self._attr_available = device in self.api_object.devices.values()

    @property
    def _common_device_identifier(self) -> str:
        return f"property_intercom__{self._internal_object.id}"

    @property
    def _common_device_name(self) -> str:
        """Return the name of this camera."""
        intercom_device = self._internal_object
        return (
            intercom_device.renamed_name
            or intercom_device.human_name
            or intercom_device.name
            or "Intercom " + str(intercom_device.id)
        )


class BasePikIntercomIotIntercomEntity(BasePikIntercomEntity[PikIntercomIotIntercomsUpdateCoordinator, PikIotIntercom]):
    UNIQUE_ID_FORMAT = "iot_intercom__{}"

    @property
    def _common_device_name(self) -> str:
        return (d := self._internal_object).name or f"IoT Intercom {d.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_intercom__{self._internal_object.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = self._internal_object in self.api_object.iot_intercoms.values()


class BasePikIntercomIotRelayEntity(BasePikIntercomEntity[PikIntercomIotIntercomsUpdateCoordinator, PikIotRelay]):
    UNIQUE_ID_FORMAT = "iot_relay__{}"

    @property
    def _common_device_name(self) -> str:
        return (d := self._internal_object).friendly_name or f"IoT Relay {d.id}"

    @property
    def related_iot_intercom(self) -> Optional["PikIotIntercom"]:
        current_relay = self._internal_object
        for intercom in self.api_object.iot_intercoms.values():
            for relay in intercom.relays or ():
                if relay is current_relay:
                    return intercom

    @property
    def _common_device_identifier(self) -> str:
        if iot_intercom := self.related_iot_intercom:
            return f"iot_intercom__{iot_intercom.id}"
        return f"iot_relay__{self._internal_object.id}"

    @callback
    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = (device := self._internal_object) in self.api_object.iot_relays.values()
        self._attr_extra_state_attributes.update(
            {
                "original_name": device.name,
                "custom_name": device.custom_name,
                "is_favorite": device.is_favorite,
                "is_hidden": device.is_hidden,
            }
        )


class BasePikIntercomIotMeterEntity(BasePikIntercomEntity[PikIntercomIotIntercomsUpdateCoordinator, PikIotMeter]):
    UNIQUE_ID_FORMAT = "iot_meter__{}"

    @property
    def _common_device_name(self) -> str:
        return (d := self._internal_object).title or f"IoT Meter {d.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_meter__{self._internal_object.id}"

    @callback
    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        # self._attr_available = (device := self._internal_object) in self.api_object.iot_meters.values()
        self._attr_available = True
        self._attr_extra_state_attributes.update(
            {
                "serial": device.serial,
                "kind": device.kind,
                "pipe_identifier": device.pipe_identifier,
            }
        )


class BasePikIntercomIotCameraEntity(BasePikIntercomEntity[PikIntercomIotCamerasUpdateCoordinator, PikIotCamera]):
    UNIQUE_ID_FORMAT = "iot_camera__{}"

    @property
    def _common_device_name(self) -> str:
        return (device := self._internal_object).name or f"IoT Camera {device.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_camera__{self._internal_object.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = self._internal_object in self.api_object.iot_cameras.values()


class BasePikIntercomLastCallSessionEntity(
    BasePikIntercomEntity[PikIntercomLastCallSessionUpdateCoordinator, Optional[PikActiveCallSession]]
):
    UNIQUE_ID_FORMAT = "last_call_session__{}"

    @property
    def _common_device_identifier(self) -> str:
        return BasePikIntercomLastCallSessionEntity.UNIQUE_ID_FORMAT.format(
            self.coordinator.config_entry.entry_id,
        )

    @property
    def _common_device_name(self) -> str:
        return "Last Call Session"

    @callback
    def _update_unique_id(self) -> None:
        self._attr_unique_id = self.UNIQUE_ID_FORMAT.format(self.coordinator.config_entry.entry_id)

    @callback
    def _update_attr(self) -> None:
        self._internal_object = self.coordinator.data
        self._attr_available = self._internal_object is not None
        super()._update_attr()
