import asyncio
import logging
import re
from abc import ABC, abstractmethod
from datetime import timedelta
from functools import partial
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
    Mapping,
    Sequence,
    Iterable,
    Callable,
)

from homeassistant.const import ATTR_ID, ATTR_LOCATION, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
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
    ATTR_SERIAL,
    ATTR_KIND,
    ATTR_PIPE_IDENTIFIER,
    CONF_ADD_SUGGESTED_AREAS,
)
from custom_components.pik_intercom.helpers import (
    ConfigEntryLoggerAdapter,
    AnyLogger,
    get_logger,
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
    BaseObject,
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
        logger: AnyLogger = _LOGGER,
        retries: int = 3,
    ) -> None:
        """Initialize Pik Intercom personal intercoms data updater."""
        self.api_object = api_object
        self.update_retries = retries

        if isinstance(logger, logging.Logger):
            logger = ConfigEntryLoggerAdapter(logger)

        # noinspection PyTypeChecker
        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=update_interval,
        )

    def get_entities_dict(
        self, entity_cls: Type["BasePikEntity"]
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
                self.logger.debug(f"Retrying request due to error: {exc}")
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
        self.logger.debug("Performing last call session update")

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


class BasePikDictUpdateCoordinator(BasePikUpdateCoordinator[None], ABC):
    update_target_description: str = "<unknown>"

    @abstractmethod
    async def _async_update_internal_dict(self) -> Mapping[Hashable, Any]:
        raise NotImplementedError

    async def _async_update_internal(self) -> None:
        self.logger.debug(
            f"Fetching data for {self.update_target_description}"
        )
        dict_items = await self._async_update_internal_dict()
        self.logger.debug(
            f"Successfully fetched {self.update_target_description} data "
            f"for {len(dict_items)} entries: "
            f"{', '.join(map(str, dict_items))}"
        )


class BasePikIcmUpdateCoordinator(BasePikDictUpdateCoordinator, ABC):
    def __init__(
        self,
        *args,
        object_id: int,
        **kwargs,
    ) -> None:
        self.object_id = object_id
        if "{}" in self.update_target_description:
            self.update_target_description = (
                self.update_target_description.format(self.object_id)
            )
        super().__init__(*args, **kwargs)


class PikIcmIntercomUpdateCoordinator(BasePikIcmUpdateCoordinator):
    update_target_description = "ICM intercom {}"

    async def _async_update_internal_dict(self) -> Mapping[int, IcmIntercom]:
        """Fetch data."""

        # imitate mapping for better logging
        return {
            self.object_id: await self.api_object.icm_update_intercom(
                self.object_id
            )
        }


class PikIcmPropertyUpdateCoordinator(BasePikIcmUpdateCoordinator):
    update_target_description = "ICM property {}"

    async def _async_update_internal_dict(self) -> Mapping[int, IcmIntercom]:
        """Fetch data."""
        return await self.api_object.icm_update_intercoms(self.object_id)


class PikIotIntercomsUpdateCoordinator(BasePikDictUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    update_target_description = "IoT intercoms"

    async def _async_update_internal_dict(self) -> Mapping[int, IotIntercom]:
        """Fetch data IoT intercoms data."""
        return await self.api_object.iot_update_intercoms()


class PikIotCamerasUpdateCoordinator(BasePikDictUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    update_target_description = "IoT cameras"

    async def _async_update_internal_dict(self) -> Mapping[int, IotCamera]:
        """Fetch data."""
        return await self.api_object.iot_update_cameras()


class PikIotMetersUpdateCoordinator(BasePikDictUpdateCoordinator):
    """Class to manage fetching Pik Intercom IoT data."""

    update_target_description = "IoT meters"

    async def _async_update_internal_dict(self) -> Mapping[int, IotMeter]:
        """Fetch data."""
        return await self.api_object.iot_update_meters()


_TBasePikUpdateCoordinator = TypeVar(
    "_TBasePikUpdateCoordinator",
    bound=BasePikUpdateCoordinator,
)

_TBaseObject = TypeVar("_TBaseObject", bound=BaseObject)


class BasePikEntity(
    CoordinatorEntity[_TBasePikUpdateCoordinator],
    ABC,
    Generic[_TBasePikUpdateCoordinator, _TBaseObject],
):
    UNIQUE_ID_FORMAT: ClassVar[Optional[str]] = None

    _attr_has_entity_name = True

    def __init__(
        self,
        *args,
        entity_description: Optional[EntityDescription] = None,
        device: _TBaseObject,
        logger: AnyLogger = _LOGGER,
        **kwargs,
    ) -> None:
        self.logger = logger
        self._internal_object = device
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

        device_info = DeviceInfo(
            name=self.common_device_name,
            model=self.common_device_model,
            identifiers={(DOMAIN, self.common_device_identifier)},
            manufacturer=self.common_device_manufacturer,
            # suggested_area=getattr(self._internal_object, "geo_unit_short_name", None),
        )

        if self.coordinator.config_entry.options.get(CONF_ADD_SUGGESTED_AREAS):
            device_info["suggested_area"] = self.common_suggested_area

        self._attr_device_info = device_info

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

    @property
    def common_device_model(self) -> Optional[str]:
        """Device model used across inherent devices."""
        return None

    @property
    def common_suggested_area(self) -> Optional[str]:
        return None

    @property
    def common_device_manufacturer(self) -> str:
        return MANUFACTURER


class BasePikIcmIntercomEntity(
    BasePikEntity[PikIcmIntercomUpdateCoordinator, IcmIntercom]
):
    UNIQUE_ID_FORMAT = "icm_intercom__{}"

    @property
    def common_device_name(self) -> str:
        """Return the name of this camera."""
        intercom_device = self._internal_object
        return (
            intercom_device.renamed_name
            or intercom_device.human_name
            or intercom_device.name
            or "ICM Intercom " + str(intercom_device.id)
        )

    @property
    def common_suggested_area(self) -> Optional[str]:
        return self._internal_object.building.address

    @property
    def common_device_model(self) -> str:
        device = self._internal_object
        model = "(ICM) " + (
            DEVICE_KIND_TRANSLATIONS.get(device.kind, device.kind) or "-"
        )
        if (mode := device.mode) not in ("1", 1, None):
            model += " (" + str(mode) + ")"
        return model

    @property
    def common_device_manufacturer(self) -> str:
        device = self._internal_object
        return (
            DEVICE_CATEGORY_TRANSLATIONS.get(
                device.device_category, device.device_category
            )
            or super().common_device_manufacturer
        )


class BasePikIotIntercomEntity(
    BasePikEntity[PikIotIntercomsUpdateCoordinator, IotIntercom]
):
    UNIQUE_ID_FORMAT = "iot_intercom__{}"

    @classmethod
    def get_intercom_common_device_name(cls, device: IotIntercom) -> str:
        return device.name or f"IoT Intercom {device.id}"

    @classmethod
    def get_intercom_common_suggested_area(
        cls, device: IotIntercom
    ) -> Optional[str]:
        for relay in device.relays:
            if geo_unit := relay.property_geo_unit:
                return geo_unit[1].rpartition(",")[0] or None

    @property
    def common_device_name(self) -> str:
        return self.get_intercom_common_device_name(self._internal_object)

    @property
    def common_device_model(self) -> str:
        return "(IoT) Intercom"


class BasePikIotRelayEntity(
    BasePikEntity[PikIotIntercomsUpdateCoordinator, IotRelay]
):
    UNIQUE_ID_FORMAT = "iot_relay__{}"

    @property
    def common_device_name(self) -> str:
        if iot_intercom := self._internal_object.intercom:
            return BasePikIotIntercomEntity.get_intercom_common_device_name(
                iot_intercom
            )
        return (
            d := self._internal_object
        ).friendly_name or f"IoT Relay {d.id}"

    @property
    def common_device_identifier(self) -> str:
        if iot_intercom := self._internal_object.intercom:
            return BasePikIotIntercomEntity.UNIQUE_ID_FORMAT.format(
                iot_intercom.id
            )
        return super().common_device_identifier

    @property
    def common_suggested_area(self) -> Optional[str]:
        if iot_intercom := self._internal_object.intercom:
            return BasePikIotIntercomEntity.get_intercom_common_suggested_area(
                iot_intercom
            )
        if not (geo_unit := self._internal_object.property_geo_unit):
            return
        return geo_unit[1].rpartition(",")[0] or None

    @property
    def common_device_model(self) -> str:
        if self._internal_object.intercom:
            return "(IoT) Intercom"
        return "(IoT) Relay"

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


class BasePikIotMeterEntity(
    BasePikEntity[PikIotIntercomsUpdateCoordinator, IotMeter]
):
    UNIQUE_ID_FORMAT = "iot_meter__{}"

    @property
    def common_device_name(self) -> str:
        return (d := self._internal_object).title or f"IoT Meter {d.id}"

    @property
    def common_device_model(self) -> str:
        return "(IoT) Meter"

    @callback
    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        # self._attr_available = (device := self._internal_object) in self.api_object.iot_meters.values()
        self._attr_available = True
        self._attr_extra_state_attributes.update(
            {
                ATTR_SERIAL: device.serial,
                ATTR_KIND: device.kind,
                ATTR_PIPE_IDENTIFIER: device.pipe_identifier,
            }
        )


class BasePikIotCameraEntity(
    BasePikEntity[PikIotCamerasUpdateCoordinator, IotCamera]
):
    UNIQUE_ID_FORMAT = "iot_camera__{}"

    @property
    def common_device_name(self) -> str:
        return (
            device := self._internal_object
        ).name or f"IoT Camera {device.id}"

    @property
    def common_device_model(self) -> str:
        return "(IoT) Camera"

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_available = (
            self._internal_object in self.api_object.iot_cameras.values()
        )


CAMEL_CASE_PATTERN: Final = re.compile(r"(?<!^)(?=[A-Z])")


class BasePikLastCallSessionEntity(
    BasePikEntity[
        PikLastCallSessionUpdateCoordinator,
        LCSCoordinatorReturnType,
    ]
):
    UNIQUE_ID_FORMAT = "last_call_session__{}"

    @property
    def common_device_identifier(self) -> str:
        """This sensor is tied to a config entry."""
        return BasePikLastCallSessionEntity.UNIQUE_ID_FORMAT.format(
            self.api_object.account.id,
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
        self._attr_extra_state_attributes[ATTR_TYPE] = (
            CAMEL_CASE_PATTERN.sub("_", o.__class__.__name__).lower()
            if (o := self._internal_object)
            else None
        )


_TUpdateCoordinator = TypeVar(
    "_TUpdateCoordinator", bound=BasePikUpdateCoordinator
)
EntityClassType = Type[BasePikEntity[_TUpdateCoordinator, _TBaseObject]]
ContainerType = Mapping[Hashable, _TBaseObject]


@callback
def async_add_entities_iteration(
    coordinator: _TUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
    containers: ContainerType | Sequence[ContainerType],
    entity_classes: EntityClassType | Sequence[EntityClassType],
    entity_descriptions: Iterable[EntityDescription] | None = None,
    item_checker: Callable[[_TBaseObject], bool] = lambda x: True,
    *,
    logger: AnyLogger = _LOGGER,
) -> None:
    logger = get_logger(logger)

    entities = coordinator.get_entities_dict(entity_classes)
    domain = async_get_current_platform().domain

    if isinstance(containers, Mapping):
        containers = (containers,)
    if isinstance(entity_classes, type):
        entity_classes = [entity_classes] * len(containers)
    elif len(entity_classes) != len(containers):
        raise ValueError("entity_classes and contains must be of same length")

    new_entities = []
    for entity_class, container in zip(entity_classes, containers):
        added_device_ids = set()
        for entity_description in entity_descriptions or (None,):
            for item_id, item in container.items():
                if not item_checker(item):
                    continue
                key = (
                    item_id,
                    entity_description.key if entity_description else None,
                )
                if key in entities:
                    continue

                added_device_ids.add(item_id)
                entities[key] = entity = entity_class(
                    coordinator,
                    device=item,
                    entity_description=entity_description,
                    logger=logger,
                )
                new_entities.append(entity)
        if added_device_ids:
            logger.debug(
                f"Adding {entity_class.__name__} {domain}s for {added_device_ids}"
            )

    if new_entities:
        async_add_entities(new_entities)


@callback
def async_add_entities_with_listener(
    coordinator: BasePikUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
    containers: ContainerType | Sequence[ContainerType],
    entity_classes: EntityClassType | Sequence[EntityClassType],
    entity_descriptions: Iterable[EntityDescription] | None = None,
    item_checker: Callable[[_TBaseObject], bool] = lambda x: True,
    *,
    logger: AnyLogger = _LOGGER,
) -> None:
    add_call = partial(
        async_add_entities_iteration,
        coordinator,
        async_add_entities,
        containers,
        entity_classes,
        entity_descriptions,
        item_checker,
        logger=logger,
    )

    add_call()

    coordinator.async_add_listener(add_call)
