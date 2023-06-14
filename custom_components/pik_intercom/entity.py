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

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity,
)

from custom_components.pik_intercom.const import DOMAIN, MANUFACTURER
from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikPropertyDevice,
    PikIotIntercom,
    PikIotRelay,
    PikIotMeter,
    PikIotCamera,
)

if TYPE_CHECKING:
    # noinspection PyUnresolvedReferences
    from custom_components.pik_intercom.api import _BaseObject

_LOGGER = logging.getLogger(__name__)


class BasePikIntercomUpdateCoordinator(DataUpdateCoordinator[None], ABC):
    """Base class for update coordinators used by Pik Intercom integration"""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api_object: "PikIntercomAPI",
        update_interval: Optional[timedelta] = None,
    ) -> None:
        """Initialize Pik Intercom personal intercoms data updater."""
        self.api_object = api_object

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    @abstractmethod
    async def _async_update_internal(self) -> None:
        raise NotImplementedError

    async def _async_update_data(self) -> None:
        """Fetch data."""
        try:
            await self._async_update_internal()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            msg = f"Unable to fetch data: {exc}"
            raise UpdateFailed(msg) from exc


class PikIntercomPropertyIntercomsUpdateCoordinator(BasePikIntercomUpdateCoordinator):
    def __init__(
        self,
        *args,
        property_id: int,
        **kwargs,
    ) -> None:
        self.property_id = property_id
        super().__init__(*args, **kwargs)

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        await self.api_object.async_update_property_intercoms(self.property_id)


class PikIntercomIotIntercomsUpdateCoordinator(BasePikIntercomUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        await self.api_object.async_update_iot_intercoms()


class PikIntercomIotCamerasUpdateCoordinator(BasePikIntercomUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        await self.api_object.async_update_iot_cameras()


class PikIntercomIotMetersUpdateCoordinator(BasePikIntercomUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        await self.api_object.async_update_iot_meters()


_TBasePikIntercomUpdateCoordinator = TypeVar(
    "_TBasePikIntercomUpdateCoordinator",
    bound=BasePikIntercomUpdateCoordinator,
)

_TBaseObject = TypeVar("_TBaseObject", bound="_BaseObject")


class BasePikIntercomDeviceEntity(Entity, Generic[_TBaseObject]):
    UNIQUE_ID_FORMAT: ClassVar[Optional[str]] = None

    def __init__(self, *args, device: _TBaseObject, **kwargs) -> None:
        self._internal_object: _TBaseObject = device
        super().__init__(*args, **kwargs)
        if self.UNIQUE_ID_FORMAT:
            self._attr_unique_id = self.UNIQUE_ID_FORMAT.format(device.id)
        self._update_attr()

    @callback
    def _update_attr(self) -> None:
        """Update the state and attributes."""
        self._attr_name = self._common_device_name
        self._attr_device_info = DeviceInfo(
            name=self._attr_name,
            identifiers={(DOMAIN, self._common_device_identifier)},
            manufacturer=MANUFACTURER,
            # suggested_area=getattr(self._internal_object, "geo_unit_short_name", None),
        )

    @property
    @abstractmethod
    def _common_device_identifier(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def _common_device_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def api_object(self) -> "PikIntercomAPI":
        raise NotImplementedError


class BasePikIntercomCoordinatorEntity(
    BasePikIntercomDeviceEntity[_TBaseObject],
    CoordinatorEntity[_TBasePikIntercomUpdateCoordinator],
    ABC,
    Generic[_TBasePikIntercomUpdateCoordinator, _TBaseObject],
):
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


class BasePikIntercomPropertyDeviceEntity(
    BasePikIntercomCoordinatorEntity[PikPropertyDevice, PikIntercomPropertyIntercomsUpdateCoordinator]
):
    UNIQUE_ID_FORMAT = "property_intercom__{}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_device_info.update(
            manufacturer=device.device_category or MANUFACTURER,
            model=f"{device.kind or '-'} / {device.mode or '-'}",
        )
        self._attr_extra_state_attributes = {
            "id": device.id,
            "face_detection": device.face_detection,
            "sip_proxy_server": device.proxy,
            "sip_proxy_user": device.ex_user,
        }
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


class BasePikIntercomIotIntercomEntity(
    BasePikIntercomCoordinatorEntity[PikIotIntercom, PikIntercomIotIntercomsUpdateCoordinator]
):
    UNIQUE_ID_FORMAT = "iot_intercom__{}"

    @property
    def _common_device_name(self) -> str:
        return (d := self._internal_object).name or f"IoT Intercom {d.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_intercom__{self._internal_object.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_available = device in self.api_object.iot_intercoms.values()
        self._attr_extra_state_attributes = {
            "id": device.id,
            "face_detection": device.is_face_detection,
            "sip_proxy_server": device.proxy,
            "sip_proxy_user": device.ex_user,
            "snapshot_url": device.snapshot_url,
            "stream_url": device.stream_url,
        }

    @property
    def base_name(self) -> str:
        iot_intercom = self._internal_object
        return iot_intercom.name or f"IoT Intercom {iot_intercom.id}"


class BasePikIntercomIotRelayEntity(
    BasePikIntercomCoordinatorEntity[PikIotRelay, PikIntercomIotIntercomsUpdateCoordinator]
):
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

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_available = device.id in self.api_object.iot_relays
        self._attr_extra_state_attributes = {
            "id": device.id,
            "original_name": device.name,
            "custom_name": device.custom_name,
            "is_favorite": device.is_favorite,
            "is_hidden": device.is_hidden,
            "snapshot_url": device.snapshot_url,
            "stream_url": device.stream_url,
        }


class BasePikIntercomIotMeterEntity(
    BasePikIntercomCoordinatorEntity[PikIotMeter, PikIntercomIotIntercomsUpdateCoordinator]
):
    UNIQUE_ID_FORMAT = "iot_meter__{}"

    @property
    def _common_device_name(self) -> str:
        return (d := self._internal_object).title or f"IoT Meter {d.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_meter__{self._internal_object.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_available = device.id in self.api_object.iot_meters
        self._attr_extra_state_attributes = {
            "id": device.id,
            "serial": device.serial,
            "kind": device.kind,
            "pipe_identifier": device.pipe_identifier,
        }


class BasePikIntercomIotCameraEntity(
    BasePikIntercomCoordinatorEntity[PikIotCamera, PikIntercomIotCamerasUpdateCoordinator]
):
    UNIQUE_ID_FORMAT = "iot_camera__{}"

    @property
    def _common_device_name(self) -> str:
        return (device := self._internal_object).name or f"IoT Camera {device.id}"

    @property
    def _common_device_identifier(self) -> str:
        return f"iot_camera__{self._internal_object.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        self._attr_available = device.id in self.api_object.iot_cameras
        self._attr_extra_state_attributes = {
            "id": device.id,
            "geo_unit": device.geo_unit_short_name,
            "snapshot_url": device.snapshot_url,
            "stream_url": device.stream_url,
        }
