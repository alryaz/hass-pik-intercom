import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import (
    TypeVar,
    Any,
    Generic,
    Optional,
    ClassVar,
    Type,
    Hashable,
    Final,
    Literal,
)

from homeassistant.const import ATTR_ID, ATTR_LOCATION, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity,
)

from custom_components.pik_intercom.const import (
    DOMAIN,
    MANUFACTURER,
    DATA_ENTITIES,
    ATTR_TYPE,
)
from pik_intercom import (
    IcmIntercom,
    IotIntercom,
    IotRelay,
    IotMeter,
    IotCamera,
    IotActiveCallSession,
    IcmCallSession,
    IotCallSession,
    IcmActiveCallSession,
)
from pik_intercom import PikIntercomAPI

_LOGGER = logging.getLogger(__name__)

DEVICE_CATEGORY_TRANSLATIONS: Final = {
    "rusguard": "RusGuard",
    "call_panel": "Generic Call Panel",
}

DEVICE_KIND_TRANSLATIONS: Final = {
    "for_entrance": "Outdoor Access Panel",
    "for_floor": "Floor Access Panel",
}

DEVICE_MODE_TRANSLATIONS: Final = {
    "left_door": "Left Door",
    "right_door": "Right Door",
    "one_door": "One Door",
}

_T = TypeVar("_T")


class BasePikUpdateCoordinator(DataUpdateCoordinator[_T], ABC, Generic[_T]):
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

    def get_entities_dict(
        self, entity_cls: Type["BasePikIntercomEntity"]
    ) -> dict[Hashable, Any]:
        return self.hass.data[DATA_ENTITIES].setdefault(entity_cls, {})

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
                # Sleep for two seconds between requests
                _LOGGER.debug(
                    f"[{self.config_entry.entry_id[-6:]}] Retrying request due to error: {exc}"
                )
                await asyncio.sleep(2)


LCSCoordinatorReturnType = (
    IotActiveCallSession
    | IotCallSession
    | IcmActiveCallSession
    | IcmCallSession
    | Literal[False]
    | None
)


class PikLastCallSessionUpdateCoordinator(
    BasePikUpdateCoordinator[LCSCoordinatorReturnType]
):
    async def _async_update_internal(
        self,
    ) -> LCSCoordinatorReturnType:
        """Fetch data."""
        eid = self.config_entry.entry_id[-6:]
        _LOGGER.debug(f"[{eid}] Performing last call session update")

        if last_call_session := await (
            api := self.api_object
        ).fetch_last_active_session():
            return last_call_session

        if (data := self.data) is False:
            return None

        # @TODO: work on less frequent requests for this case
        if data is not None:
            return data

        tasks = [
            self.hass.loop.create_task(api.iot_update_call_sessions(1)),
            self.hass.loop.create_task(api.icm_update_call_sessions(1)),
        ]

        await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

        iot_result, icm_result = tasks[0].result(), tasks[1].result()

        if isinstance(iot_result, BaseException) and isinstance(
            icm_result, BaseException
        ):
            raise iot_result
        if not (last_call_session := api.get_last_call_session()):
            return False
        return last_call_session


class PikIcmIntercomUpdateCoordinator(BasePikUpdateCoordinator[None]):
    def __init__(
        self,
        *args,
        intercom_id: int,
        **kwargs,
    ) -> None:
        self.intercom_id = intercom_id
        super().__init__(*args, **kwargs)

    @property
    def intercom(self):
        return self.api_object.icm_intercoms[self.intercom_id]

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        _LOGGER.debug(
            f"[{self.config_entry.entry_id[-6:]}] Updating ICM intercom {self.intercom_id}"
        )
        await self.api_object.icm_update_intercom(self.intercom_id)


class PikIcmPropertyUpdateCoordinator(BasePikUpdateCoordinator[None]):
    def __init__(
        self,
        *args,
        property_id: int,
        **kwargs,
    ) -> None:
        self.property_id = property_id
        super().__init__(*args, **kwargs)

    @property
    def property(self):
        return self.api_object.icm_properties[self.property_id]

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        _LOGGER.debug(
            f"[{self.config_entry.entry_id[-6:]}] Updating ICM intercoms for property {self.property_id}"
        )
        await self.api_object.icm_update_intercoms(self.property_id)


class PikIotIntercomsUpdateCoordinator(BasePikUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        _LOGGER.debug(
            f"[{self.config_entry.entry_id[-6:]}] Updating IoT intercoms"
        )
        await self.api_object.iot_update_intercoms()


class PikIotCamerasUpdateCoordinator(BasePikUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    async def _async_update_internal(self) -> Any:
        """Fetch data."""
        _LOGGER.debug(
            f"[{self.config_entry.entry_id[-6:]}] Updating IoT cameras"
        )
        await self.api_object.iot_update_cameras()


class PikIotMetersUpdateCoordinator(BasePikUpdateCoordinator[None]):
    """Class to manage fetching Pik Intercom IoT data."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.regular_update_interval = None

    async def _async_update_internal(self) -> None:
        """Fetch data."""
        eid = self.config_entry.entry_id[-6:]
        _LOGGER.debug(f"[{eid}] Updating IoT meters")
        await self.api_object.iot_update_meters()


_TBasePikIntercomUpdateCoordinator = TypeVar(
    "_TBasePikIntercomUpdateCoordinator",
    bound=BasePikUpdateCoordinator,
)

_TBaseObject = TypeVar("_TBaseObject", bound="_BaseObject")


class BasePikIntercomEntity(
    CoordinatorEntity[_TBasePikIntercomUpdateCoordinator],
    ABC,
    Generic[_TBasePikIntercomUpdateCoordinator, _TBaseObject],
):
    UNIQUE_ID_FORMAT: ClassVar[Optional[str]] = None

    _attr_has_entity_name = True

    def __init__(
        self,
        *args,
        entity_description: Optional[EntityDescription] = None,
        device: _TBaseObject,
        **kwargs,
    ) -> None:
        self._internal_object: _TBaseObject = device
        if entity_description is not None:
            self.entity_description = entity_description
        super().__init__(*args, **kwargs)
        self._update_unique_id()
        self._update_attr()

    @callback
    def _update_unique_id(self) -> None:
        self._attr_unique_id = self.UNIQUE_ID_FORMAT.format(
            self._internal_object.id
        )
        if e := self.entity_description:
            self._attr_unique_id += "__" + e.key

    @callback
    def _update_attr(self) -> None:
        """Update the state and attributes."""
        self._attr_extra_state_attributes = {}
        if device := self._internal_object:
            self._attr_extra_state_attributes[ATTR_ID] = device.id
            if hasattr(device, "geo_unit_short_name"):
                self._attr_extra_state_attributes[
                    ATTR_LOCATION
                ] = device.geo_unit_short_name
        else:
            self._attr_extra_state_attributes[ATTR_ID] = None

        self._attr_extra_state_attributes[
            ATTR_TYPE
        ] = self.unique_id.partition("__")[0]

        self._attr_device_info = DeviceInfo(
            name=self.common_device_name,
            identifiers={(DOMAIN, self.common_device_identifier)},
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
    def common_device_identifier(self) -> str:
        return self.UNIQUE_ID_FORMAT.format(self._internal_object.id)

    @property
    @abstractmethod
    def common_device_name(self) -> str:
        raise NotImplementedError

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        entities = self.coordinator.get_entities_dict(self.__class__)
        for item_id, entity in tuple(entities.items()):
            if self is entity:
                del entities[item_id]
                break


class BasePikIcmIntercomEntity(
    BasePikIntercomEntity[PikIcmIntercomUpdateCoordinator, IcmIntercom]
):
    UNIQUE_ID_FORMAT = "icm_intercom__{}"

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        model = DEVICE_KIND_TRANSLATIONS.get(device.kind, device.kind) or "-"
        if (mode := device.mode) not in ("1", 1, None):
            model += " (" + str(mode) + ")"
        self._attr_device_info.update(
            manufacturer=(
                DEVICE_CATEGORY_TRANSLATIONS.get(
                    device.device_category, device.device_category
                )
                or MANUFACTURER
            ),
            model=model,
        )
        self._attr_available = device in self.api_object.icm_intercoms.values()

    @property
    def common_device_name(self) -> str:
        """Return the name of this camera."""
        intercom_device = self._internal_object
        return (
            intercom_device.renamed_name
            or intercom_device.human_name
            or intercom_device.name
            or "Intercom " + str(intercom_device.id)
        )


class BasePikIntercomIotIntercomEntity(
    BasePikIntercomEntity[PikIotIntercomsUpdateCoordinator, IotIntercom]
):
    UNIQUE_ID_FORMAT = "iot_intercom__{}"

    @property
    def common_device_name(self) -> str:
        return (d := self._internal_object).name or f"IoT Intercom {d.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = (
            self._internal_object in self.api_object.iot_intercoms.values()
        )


class BasePikIntercomIotRelayEntity(
    BasePikIntercomEntity[PikIotIntercomsUpdateCoordinator, IotRelay]
):
    UNIQUE_ID_FORMAT = "iot_relay__{}"

    @property
    def common_device_name(self) -> str:
        return (
            d := self._internal_object
        ).friendly_name or f"IoT Relay {d.id}"

    @property
    def related_iot_intercom(self) -> Optional["IotIntercom"]:
        current_relay = self._internal_object
        for intercom in self.api_object.iot_intercoms.values():
            for relay in intercom.relays or ():
                if relay is current_relay:
                    return intercom

    @property
    def common_device_identifier(self) -> str:
        if iot_intercom := self.related_iot_intercom:
            return BasePikIntercomIotIntercomEntity.UNIQUE_ID_FORMAT.format(
                iot_intercom.id
            )
        return super().common_device_identifier

    @callback
    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = (
            device := self._internal_object
        ) in self.api_object.iot_relays.values()
        self._attr_extra_state_attributes.update(
            {
                "original_name": device.name,
                "custom_name": device.custom_name,
                "is_favorite": device.is_favorite,
                "is_hidden": device.is_hidden,
            }
        )


class BasePikIntercomIotMeterEntity(
    BasePikIntercomEntity[PikIotIntercomsUpdateCoordinator, IotMeter]
):
    UNIQUE_ID_FORMAT = "iot_meter__{}"

    @property
    def common_device_name(self) -> str:
        return (d := self._internal_object).title or f"IoT Meter {d.id}"

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


class BasePikIntercomIotCameraEntity(
    BasePikIntercomEntity[PikIotCamerasUpdateCoordinator, IotCamera]
):
    UNIQUE_ID_FORMAT = "iot_camera__{}"

    @property
    def common_device_name(self) -> str:
        return (
            device := self._internal_object
        ).name or f"IoT Camera {device.id}"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = (
            self._internal_object in self.api_object.iot_cameras.values()
        )


class BasePikLastCallSessionEntity(
    BasePikIntercomEntity[
        PikLastCallSessionUpdateCoordinator,
        LCSCoordinatorReturnType,
    ]
):
    UNIQUE_ID_FORMAT = "last_call_session__{}"

    @property
    def common_device_identifier(self) -> str:
        """This sensor is tied to a config entry."""
        return BasePikLastCallSessionEntity.UNIQUE_ID_FORMAT.format(
            self.coordinator.config_entry.entry_id,
        )

    @property
    def common_device_name(self) -> str:
        return f"Last Call Session ({self.coordinator.config_entry.data[CONF_USERNAME]})"

    def _update_unique_id(self) -> None:
        self._attr_unique_id = (
            self.common_device_identifier + "__" + self.entity_description.key
        )

    @callback
    def _update_attr(self) -> None:
        self._internal_object = self.coordinator.data
        self._attr_available = bool(self._internal_object)
        super()._update_attr()
