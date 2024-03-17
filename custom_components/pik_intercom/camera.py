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
    Final,
)

from homeassistant.components import ffmpeg
from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    CameraEntityDescription,
    StreamType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIcmIntercomEntity,
    BasePikIotIntercomEntity,
    BasePikIotRelayEntity,
    PikIotIntercomsUpdateCoordinator,
    PikIotCamerasUpdateCoordinator,
    PikIcmIntercomUpdateCoordinator,
    BasePikIotCameraEntity,
    BasePikEntity,
    PikIcmPropertyUpdateCoordinator,
    async_add_entities_with_listener,
)
from custom_components.pik_intercom.helpers import (
    get_logger,
)
from pik_intercom import (
    PikIntercomException,
    ObjectWithVideo,
    ObjectWithSnapshot,
    ObjectWithSIP,
)

_LOGGER: Final = logging.getLogger(__name__)

AnyCameraType = Union[ObjectWithVideo, ObjectWithSnapshot]


def check_has_camera(x: Union[ObjectWithVideo, ObjectWithSnapshot]) -> bool:
    return x.has_camera


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom cameras for a config entry."""
    logger = get_logger(_LOGGER)

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
            entity_classes = PikIotIntercomCamera

        else:
            continue

        async_add_entities_with_listener(
            coordinator=coordinator,
            async_add_entities=async_add_entities,
            containers=containers,
            entity_classes=entity_classes,
            item_checker=check_has_camera,
            logger=logger,
        )

    return True


class _BaseIntercomCamera(BasePikEntity, Camera, ABC):
    """Base class for Pik Intercom cameras."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = StreamType.HLS
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
                    self.logger.debug(
                        f"Изменение URL потока: {stream.source} ---> {stream_source}"
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
                    if snapshot_image := await internal_object.get_snapshot():
                        return snapshot_image
                except PikIntercomException as error:
                    _LOGGER.debug(
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
    BasePikIotCameraEntity, _BaseIntercomCamera
):
    """Entity representation of a singleton camera."""

    entity_description = CameraEntityDescription(
        key="camera",
        icon="mdi:cctv",
        name="Camera",
        translation_key="camera",
        has_entity_name=True,
    )


class PikIotIntercomCamera(BasePikIotIntercomEntity, _BaseIntercomCamera):
    """Entity representation of an IoT intercom camera."""

    _attr_entity_registry_enabled_default = False

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_extra_state_attributes[
            "relay_ids"
        ] = self._internal_object.relay_ids


class PikIotRelayCamera(BasePikIotRelayEntity, _BaseIntercomCamera):
    """Entity representation of an IoT relay camera."""

    def _update_attr(self) -> None:
        super()._update_attr()
        intercom = self._internal_object.intercom
        self._attr_extra_state_attributes["intercom_id"] = (
            intercom.id if intercom else None
        )
        self._attr_frontend_stream_type = (
            StreamType.WEB_RTC
            if intercom and intercom.webrtc_supported
            else StreamType.HLS
        )
