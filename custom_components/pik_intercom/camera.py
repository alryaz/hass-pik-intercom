"""This component provides basic support for Pik Intercom IP intercoms."""
__all__ = (
    "async_setup_entry",
    "PikIcmIntercomCamera",
    "PikIotRelayCamera",
    "PikIotIntercomCamera",
)

import asyncio
import logging
from abc import ABC
from typing import (
    Optional,
    Union,
    TypeVar,
    Generic,
)

from homeassistant.components import ffmpeg
from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    CameraEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIcmIntercomEntity,
    BasePikIntercomIotIntercomEntity,
    BasePikIntercomIotRelayEntity,
    PikIotIntercomsUpdateCoordinator,
    PikIotCamerasUpdateCoordinator,
    PikIcmIntercomUpdateCoordinator,
    BasePikIntercomIotCameraEntity,
    BasePikIntercomEntity,
    PikIcmPropertyUpdateCoordinator,
)
from custom_components.pik_intercom.helpers import (
    async_add_entities_with_listener,
)
from pik_intercom import (
    PikIntercomException,
    ObjectWithVideo,
    ObjectWithSnapshot,
    ObjectWithSIP,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

AnyCameraType = Union[ObjectWithVideo, ObjectWithSnapshot]


@callback
def _async_add_new_iot_intercoms(
    coordinator: PikIotIntercomsUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities_intercoms = coordinator.get_entities_dict(PikIotIntercomCamera)
    entities_relays = coordinator.get_entities_dict(PikIotRelayCamera)

    new_entities = []
    for intercom_id, intercom in coordinator.api_object.iot_intercoms.items():
        if intercom_id not in entities_intercoms and intercom.has_camera:
            entity = PikIotIntercomCamera(
                coordinator,
                device=intercom,
            )
            new_entities.append(entity)
            entities_intercoms[intercom_id] = entity

    for relay_id, relay in coordinator.api_object.iot_relays.items():
        if relay_id not in entities_relays and relay.has_camera:
            entity = PikIotRelayCamera(
                coordinator,
                device=relay,
            )
            new_entities.append(entity)
            entities_relays[relay_id] = entity

    if new_entities:
        async_add_entities(new_entities)


def check_has_camera(x: Union[ObjectWithVideo, ObjectWithSnapshot]) -> bool:
    return x.has_camera


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom cameras for a config entry."""
    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(
            coordinator,
            (PikIcmIntercomUpdateCoordinator, PikIcmPropertyUpdateCoordinator),
        ):
            containers = coordinator.api_object.icm_intercoms
            entity_classes = PikIcmIntercomCamera
        elif isinstance(coordinator, PikIotIntercomsUpdateCoordinator):
            containers = (
                coordinator.api_object.iot_intercoms,
                coordinator.api_object.iot_relays,
            )
            entity_classes = (PikIotIntercomCamera, PikIotRelayCamera)
        elif isinstance(coordinator, PikIotCamerasUpdateCoordinator):
            containers = coordinator.api_object.iot_cameras
            entity_classes = PikIcmIntercomCamera

        else:
            continue

        async_add_entities_with_listener(
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            containers=containers,
            entity_classes=entity_classes,
            item_checker=check_has_camera,
            logger=_LOGGER,
        )

    return True


_T = TypeVar("_T")
_TT = TypeVar("_TT")


class _BaseIntercomCamera(
    BasePikIntercomEntity[_T, _TT], Camera, ABC, Generic[_T, _TT]
):
    """Base class for Pik Intercom cameras."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_motion_detection_enabled = False

    entity_description = CameraEntityDescription(
        key="camera",
        icon="mdi:doorbell-video",
        name="Intercom",
        translation_key="intercom",
        has_entity_name=True,
    )

    def __init__(self, *args, **kwargs) -> None:
        Camera.__init__(self)
        super().__init__(*args, **kwargs)

        # self._ffmpeg = self.hass.data[ffmpeg.DATA_FFMPEG]
        self._does_not_require_tcp_transport: Optional[bool] = None

    def _update_attr(self) -> None:
        """Update attributes for Pik Intercom camera entity."""
        super()._update_attr()

        device = self._internal_object
        if not (
            extra_state_attributes := getattr(
                self, "_attr_extra_state_attributes", None
            )
        ):
            self._attr_extra_state_attributes = extra_state_attributes = {}

        if isinstance(device, ObjectWithVideo):
            extra_state_attributes[
                "stream_url"
            ] = stream_source = device.stream_url
            if stream := self.stream:
                if stream_source != stream.source:
                    _LOGGER.debug(
                        f"[{self._attr_unique_id}] Изменение URL потока: {stream.source} ---> {stream_source}"
                    )
                    stream.source = stream_source
                    setattr(stream, "_fast_restart_once", True)

        if isinstance(device, ObjectWithSnapshot):
            extra_state_attributes["snapshot_url"] = device.snapshot_url

        if isinstance(device, ObjectWithSIP):
            extra_state_attributes["sip_user"] = device.sip_user
            extra_state_attributes["sip_password"] = device.sip_password

        if hasattr(device, "is_face_detection"):
            extra_state_attributes["face_detection"] = device.is_face_detection

    def turn_off(self) -> None:
        raise HomeAssistantError("Binary state not supported")

    def turn_on(self) -> None:
        raise HomeAssistantError("Binary state not supported")

    def enable_motion_detection(self) -> None:
        raise HomeAssistantError("Motion detection not supported")

    def disable_motion_detection(self) -> None:
        raise HomeAssistantError("Motion detection not supported")

    async def async_camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        """Return a still image response from the camera."""
        internal_object = self._internal_object
        log_prefix = f"[{self.entity_id}] "

        # Attempt to retrieve snapshot image using photo URL
        if isinstance(internal_object, ObjectWithSnapshot):
            if photo_url := internal_object.snapshot_url:
                try:
                    # Send the request to snap a picture and return raw JPEG data
                    if (
                        snapshot_image := await internal_object.async_get_snapshot()
                    ):
                        return snapshot_image
                except PikIntercomException as error:
                    _LOGGER.error(
                        log_prefix + f"Ошибка получения снимка: {error}"
                    )

        if isinstance(internal_object, ObjectWithVideo):
            # Attempt to retrieve snapshot image using RTSP stream
            if (stream_url := internal_object.stream_url) and (
                snapshot_image := await ffmpeg.async_get_image(
                    self.hass,
                    stream_url,
                    extra_cmd="-prefix_rtsp_flags prefer_tcp",
                    width=width,
                    height=height,
                )
            ):
                return snapshot_image

        # Warn about missing sources
        _LOGGER.warning(log_prefix + "Отсутствует источник снимков")
        return None

    def camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        return asyncio.run_coroutine_threadsafe(
            self.async_camera_image(width, height),
            self.hass.loop,
        ).result()

    async def stream_source(self) -> Optional[str]:
        """Return the RTSP stream source."""
        if isinstance(self._internal_object, ObjectWithVideo):
            return self._internal_object.stream_url


class PikIcmIntercomCamera(_BaseIntercomCamera, BasePikIcmIntercomEntity):
    """Entity representation of a property device camera."""

    def _update_attr(self) -> None:
        super()._update_attr()
        device = self._internal_object
        if intercom_streams := device.video:
            state_attributes = self._attr_extra_state_attributes
            for key in intercom_streams:
                for value in intercom_streams.getall(key):
                    state_attributes[f"stream_url_{key}"] = value


class PikIntercomIotDiscreteCamera(
    BasePikIntercomIotCameraEntity, _BaseIntercomCamera
):
    """Entity representation of a singleton camera."""

    entity_description = CameraEntityDescription(
        key="camera",
        icon="mdi:cctv",
        name="Camera",
        translation_key="camera",
        has_entity_name=True,
    )


class PikIotIntercomCamera(
    BasePikIntercomIotIntercomEntity, _BaseIntercomCamera
):
    """Entity representation of an IoT intercom camera."""

    _attr_entity_registry_enabled_default = False

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_extra_state_attributes["relay_ids"] = [
            relay.id for relay in self._internal_object.relays
        ]


class PikIotRelayCamera(BasePikIntercomIotRelayEntity, _BaseIntercomCamera):
    """Entity representation of an IoT relay camera."""

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_extra_state_attributes["intercom_id"] = (
            intercom.id if (intercom := self.related_iot_intercom) else None
        )
