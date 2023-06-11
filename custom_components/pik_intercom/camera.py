"""This component provides basic support for Pik Intercom IP intercoms."""
__all__ = (
    "async_setup_entry",
    "PikIntercomPropertyDeviceCamera",
    "PikIntercomIotRelayCamera",
    "PikIntercomIotIntercomCamera",
)

import asyncio
import logging
from abc import abstractmethod, ABC
from typing import Any, Callable, Mapping, Optional, Union, Dict, List

import async_timeout
from homeassistant.components import ffmpeg
from homeassistant.components.camera import (
    CAMERA_STREAM_SOURCE_TIMEOUT,
    Camera,
    SUPPORT_STREAM,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom._base import (
    BasePikIntercomPropertyDeviceEntity,
    BasePikIntercomEntity,
    BasePikIntercomIotRelayEntity,
    BasePikIntercomIotIntercomEntity,
)
from custom_components.pik_intercom.api import (
    PikIntercomAPI,
    PikIntercomException,
    PikObjectWithVideo,
    PikObjectWithSnapshot,
)
from custom_components.pik_intercom.const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Pik Intercom camera from a config entry."""

    config_entry_id = config_entry.entry_id

    _LOGGER.debug(f"[{config_entry_id}] Настройка платформы 'camera'")

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    new_entities: List[_BaseIntercomCamera] = [
        PikIntercomPropertyDeviceCamera(hass, config_entry_id, intercom_device)
        for intercom_device in api.devices.values()
        if intercom_device.has_camera
    ]

    snapshot_urls = set()

    for iot_relay in api.iot_relays.values():
        photo_url, stream_url = iot_relay.photo_url, iot_relay.stream_url

        if photo_url:
            snapshot_urls.add(photo_url)

        if photo_url or stream_url:
            new_entities.append(
                PikIntercomIotRelayCamera(hass, config_entry_id, iot_relay)
            )

    for iot_intercom in api.iot_intercoms.values():
        photo_url = iot_intercom.photo_url

        if photo_url and photo_url not in snapshot_urls:
            new_entities.append(
                PikIntercomIotIntercomCamera(
                    hass, config_entry_id, iot_intercom
                )
            )

    async_add_entities(new_entities, True)

    _LOGGER.debug(
        f"[{config_entry_id}] Завершение инициализации платформы 'camera'"
    )

    return True


class _BaseIntercomCamera(BasePikIntercomEntity, Camera, ABC):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        Camera.__init__(self)

        self.entity_id = (
            f"camera.{self._internal_object_identifier.replace('__', '_')}"
        )

        self._entity_updater: Optional[Callable] = None
        self._ffmpeg = self.hass.data[ffmpeg.DATA_FFMPEG]
        self._does_not_require_tcp_transport: Optional[bool] = None

    @property
    @abstractmethod
    def _internal_object(
        self,
    ) -> Union[PikObjectWithVideo, PikObjectWithSnapshot]:
        raise NotImplementedError

    @property
    def icon(self) -> str:
        return "mdi:doorbell-video"

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return SUPPORT_STREAM

    @property
    def motion_detection_enabled(self) -> bool:
        """Camera Motion Detection Status."""
        return False

    @property
    def unique_id(self) -> str:
        return f"intercom_camera__{self._internal_object_identifier}"

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
            photo_url = internal_object.photo_url
            if photo_url:
                try:
                    # Send the request to snap a picture and return raw JPEG data
                    snapshot_image = await internal_object.async_get_snapshot()
                except PikIntercomException as error:
                    _LOGGER.error(
                        log_prefix + f"Ошибка получения снимка: {error}"
                    )
                else:
                    return snapshot_image
            else:
                _LOGGER.debug(log_prefix + f"Ссылка на изображение отсутствует")

        if isinstance(internal_object, PikObjectWithVideo):
            # Attempt to retrieve snapshot image using RTSP stream
            stream_url = internal_object.stream_url
            if stream_url:
                snapshot_image = await ffmpeg.async_get_image(
                    self.hass,
                    stream_url,
                    extra_cmd="-prefix_rtsp_flags prefer_tcp",
                    width=width,
                    height=height,
                )

                if not snapshot_image:
                    _LOGGER.warning(
                        log_prefix + "Видеопоток не содержит изображение"
                    )
                    return None

                return snapshot_image
            else:
                _LOGGER.debug(log_prefix + f"Ссылка на видеопоток отсутствует")

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
        internal_object = self._internal_object
        if isinstance(internal_object, PikObjectWithVideo):
            return internal_object.stream_url
        return None

    async def async_update(self) -> None:
        await super().async_update()

        stream = self.stream
        if stream:
            async with async_timeout.timeout(CAMERA_STREAM_SOURCE_TIMEOUT):
                source = await self.stream_source()
            if source != stream.source:
                _LOGGER.debug(
                    f"[{self}] Изменение URL потока: "
                    f"{stream.source} ---> {source}"
                )
                stream.update_source(source)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        internal_object = self._internal_object
        state_attributes = {}

        if isinstance(internal_object, PikObjectWithVideo):
            state_attributes["stream_url"] = internal_object.stream_url

        if isinstance(internal_object, PikObjectWithSnapshot):
            state_attributes["photo_url"] = internal_object.photo_url

        return state_attributes


class PikIntercomPropertyDeviceCamera(
    _BaseIntercomCamera, BasePikIntercomPropertyDeviceEntity
):
    """An implementation of a Pik Intercom IP intercom."""

    @property
    def _internal_object(
        self,
    ) -> Union[PikObjectWithVideo, PikObjectWithSnapshot]:
        return self._intercom_device

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        state_attributes = super().state_attributes

        intercom_device = self._intercom_device
        intercom_streams = intercom_device.video
        state_attributes.update(
            {
                "all_stream_urls": [
                    {"quality": key, "source": value}
                    for key in (
                        intercom_streams.keys() if intercom_streams else ()
                    )
                    for value in intercom_streams.getall(key)
                ],
                "face_detection": intercom_device.face_detection,
            }
        )

        return state_attributes


class PikIntercomIotIntercomCamera(
    _BaseIntercomCamera,
    BasePikIntercomIotIntercomEntity,
):
    @property
    def _internal_object(
        self,
    ) -> Union[PikObjectWithVideo, PikObjectWithSnapshot]:
        return self._iot_intercom


class PikIntercomIotRelayCamera(
    BasePikIntercomIotRelayEntity,
    _BaseIntercomCamera,
):
    @property
    def _internal_object(
        self,
    ) -> Union[PikObjectWithVideo, PikObjectWithSnapshot]:
        return self._iot_relay
