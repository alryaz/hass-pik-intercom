"""This component provides basic support for Pik Intercom IP intercoms."""
__all__ = (
    "async_setup_entry",
    "PikIntercomPropertyDeviceCamera",
    "PikIntercomIotRelayCamera",
    "PikIntercomIotIntercomCamera",
)

import asyncio
import logging
from abc import ABC
from functools import partial
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

from custom_components.pik_intercom.api import (
    PikIntercomException,
    PikObjectWithVideo,
    PikObjectWithSnapshot,
    PikObjectWithSIP,
)
from custom_components.pik_intercom.const import DOMAIN
from custom_components.pik_intercom.entity import (
    BasePikIntercomPropertyDeviceEntity,
    BasePikIntercomIotIntercomEntity,
    BasePikIntercomIotRelayEntity,
    PikIntercomIotIntercomsUpdateCoordinator,
    PikIntercomIotCamerasUpdateCoordinator,
    PikIntercomPropertyIntercomsUpdateCoordinator,
    BasePikIntercomIotCameraEntity,
    BasePikIntercomEntity,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

AnyCameraType = Union[PikObjectWithVideo, PikObjectWithSnapshot]


@callback
def _async_add_new_iot_cameras(
    coordinator: PikIntercomIotCamerasUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = coordinator.get_entities_dict(PikIntercomIotDiscreteCamera)

    new_entities = []
    for camera_id, camera in coordinator.api_object.iot_cameras.items():
        if camera_id not in entities and (
            camera.snapshot_url or camera.stream_url
        ):
            entity = PikIntercomIotDiscreteCamera(
                coordinator,
                device=camera,
            )
            new_entities.append(entity)
            entities[camera_id] = entity

    if new_entities:
        async_add_entities(new_entities)


@callback
def _async_add_new_iot_intercoms(
    coordinator: PikIntercomIotIntercomsUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities_intercoms = coordinator.get_entities_dict(
        PikIntercomIotIntercomCamera
    )
    entities_relays = coordinator.get_entities_dict(PikIntercomIotRelayCamera)

    new_entities = []
    for intercom_id, intercom in coordinator.api_object.iot_intercoms.items():
        if intercom_id not in entities_intercoms and intercom.has_camera:
            entity = PikIntercomIotIntercomCamera(
                coordinator,
                device=intercom,
            )
            new_entities.append(entity)
            entities_intercoms[intercom_id] = entity

    for relay_id, relay in coordinator.api_object.iot_relays.items():
        if relay_id not in entities_relays and relay.has_camera:
            entity = PikIntercomIotRelayCamera(
                coordinator,
                device=relay,
            )
            new_entities.append(entity)
            entities_relays[relay_id] = entity

    if new_entities:
        async_add_entities(new_entities)


@callback
def _async_add_new_property_intercoms(
    coordinator: PikIntercomPropertyIntercomsUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = coordinator.get_entities_dict(PikIntercomPropertyDeviceCamera)

    new_entities = []
    for intercom_id, intercom in coordinator.api_object.devices.items():
        if intercom_id not in entities and (
            intercom.snapshot_url or intercom.stream_url
        ):
            entity = PikIntercomPropertyDeviceCamera(
                coordinator,
                device=intercom,
            )
            new_entities.append(entity)
            entities[intercom_id] = entity

    if new_entities:
        async_add_entities(new_entities)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add a Pik Intercom cameras for a config entry."""
    for coordinator in hass.data[DOMAIN][entry.entry_id]:
        # Add update listeners to meter entity
        if isinstance(
            coordinator, PikIntercomPropertyIntercomsUpdateCoordinator
        ):
            run_func = _async_add_new_property_intercoms
        elif isinstance(coordinator, PikIntercomIotIntercomsUpdateCoordinator):
            run_func = _async_add_new_iot_intercoms
        elif isinstance(coordinator, PikIntercomIotCamerasUpdateCoordinator):
            run_func = _async_add_new_iot_cameras
        else:
            continue

        # Run first time
        run_func(coordinator, async_add_entities)

        # Add listener for future updates
        coordinator.async_add_listener(
            partial(
                run_func,
                coordinator,
                async_add_entities,
            )
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

        if isinstance(device, PikObjectWithVideo):
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

        if isinstance(device, PikObjectWithSnapshot):
            extra_state_attributes["snapshot_url"] = device.snapshot_url

        if isinstance(device, PikObjectWithSIP):
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
        if isinstance(internal_object, PikObjectWithSnapshot):
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

        if isinstance(internal_object, PikObjectWithVideo):
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
        if isinstance(self._internal_object, PikObjectWithVideo):
            return self._internal_object.stream_url


class PikIntercomPropertyDeviceCamera(
    _BaseIntercomCamera, BasePikIntercomPropertyDeviceEntity
):
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


class PikIntercomIotIntercomCamera(
    BasePikIntercomIotIntercomEntity, _BaseIntercomCamera
):
    """Entity representation of an IoT intercom camera."""

    _attr_entity_registry_enabled_default = False

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_extra_state_attributes["relay_ids"] = [
            relay.id for relay in self._internal_object.relays
        ]


class PikIntercomIotRelayCamera(
    BasePikIntercomIotRelayEntity, _BaseIntercomCamera
):
    """Entity representation of an IoT relay camera."""

    def _update_attr(self) -> None:
        super()._update_attr()
        self._attr_extra_state_attributes["intercom_id"] = (
            intercom.id if (intercom := self.related_iot_intercom) else None
        )
