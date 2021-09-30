"""This component provides basic support for Pik Domofon IP intercoms."""
import asyncio
import logging
from typing import Any, Callable, Mapping, Optional

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, SUPPORT_STREAM
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom._base import BasePikIntercomDeviceEntity
from custom_components.pik_intercom.api import PikIntercomAPI, PikIntercomException
from custom_components.pik_intercom.const import DOMAIN

__all__ = ("async_setup_entry", "PikIntercomCamera")

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistantType, config_entry, async_add_entities) -> bool:
    """Add a Dahua IP camera from a config entry."""

    config_entry_id = config_entry.entry_id

    _LOGGER.debug(f"[{config_entry_id}] Настройка платформы 'camera'")

    api: PikIntercomAPI = hass.data[DOMAIN][config_entry_id]

    async_add_entities(
        [
            PikIntercomCamera(hass, config_entry_id, intercom_device)
            for intercom_device in api.devices.values()
            if intercom_device.has_camera
        ],
        True,
    )

    return True


class PikIntercomCamera(BasePikIntercomDeviceEntity, Camera):
    """An implementation of a Pik Domofon IP intercom."""

    def __init__(self, hass: HomeAssistantType, *args, **kwargs) -> None:
        """Initialize the Pik Domofon intercom video stream."""
        BasePikIntercomDeviceEntity.__init__(self, hass, *args, **kwargs)
        Camera.__init__(self)

        self.entity_id = f"switch.{self._intercom_device.id}_camera"

        self._entity_updater: Optional[Callable] = None
        self._ffmpeg = hass.data[ffmpeg.DATA_FFMPEG]
        self._requires_tcp_transport: Optional[bool] = None

    @property
    def icon(self) -> str:
        return "mdi:doorbell-video"

    @property
    def unique_id(self):
        """Return the entity unique ID."""
        intercom_device = self._intercom_device
        return f"intercom_camera_{intercom_device.id}"

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return SUPPORT_STREAM

    @property
    def motion_detection_enabled(self) -> bool:
        """Camera Motion Detection Status."""
        return False

    @property
    def name(self):
        """Return the name of this camera."""
        intercom_device = self._intercom_device
        return intercom_device.renamed_name or intercom_device.human_name or intercom_device.name

    @property
    def device_state_attributes(self) -> Mapping[str, Any]:
        intercom_device = self._intercom_device
        intercom_streams = intercom_device.video
        return {
            "photo_url": intercom_device.photo_url,
            "stream_url": intercom_device.stream_url,
            "all_stream_urls": [
                {"quality": key, "source": value}
                for key in (intercom_streams.keys() if intercom_streams else ())
                for value in intercom_streams.getall(key)
            ],
            "face_detection": intercom_device.face_detection,
        }

    def turn_off(self) -> None:
        raise NotImplementedError

    def turn_on(self) -> None:
        raise NotImplementedError

    def enable_motion_detection(self) -> None:
        raise NotImplementedError

    def disable_motion_detection(self) -> None:
        raise NotImplementedError

    def camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        return asyncio.run_coroutine_threadsafe(
            self.async_camera_image(width, height),
            self.hass.loop,
        ).result()

    async def async_get_snapshot_by_ffmpeg(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[bytes]:
        use_tcp_transport = self._requires_tcp_transport
        snapshot_image = None
        stream_url = await self.stream_source()

        if not stream_url:
            return None

        _LOGGER.debug(
            f"[{self._config_entry_id}] Объект {self.entity_id} "
            f"запрашивает кадр через поток RTSP"
        )
        if not use_tcp_transport:
            snapshot_image = await ffmpeg.async_get_image(
                self.hass,
                stream_url,
                width=width,
                height=height,
            )
            if use_tcp_transport is not False:
                _LOGGER.debug(
                    f"[{self._config_entry_id}] Объект {self.entity_id} "
                    f"не требует передачу видео по протоколу TCP"
                )
                self._requires_tcp_transport = False

        if use_tcp_transport or snapshot_image is None:
            snapshot_image = await ffmpeg.async_get_image(
                self.hass,
                stream_url,
                extra_cmd="-input_rtsp_transport tcp",
                width=width,
                height=height,
            )
            if use_tcp_transport is not True:
                _LOGGER.debug(
                    f"[{self._config_entry_id}] Объект {self.entity_id} "
                    f"требует передачу видео по протоколу TCP"
                )
                self._requires_tcp_transport = True

        if snapshot_image is None:
            _LOGGER.debug(
                f"[{self._config_entry_id}] Объект {self.entity_id} "
                f"не получил кадр через поток RTSP"
            )

        return snapshot_image

    async def async_camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        """Return a still image response from the camera."""
        intercom_device = self._intercom_device
        log_prefix = f"[{self.entity_id}] "

        # Attempt to retrieve snapshot image using photo URL
        if intercom_device.photo_url:
            try:
                # Send the request to snap a picture and return raw JPEG data
                snapshot_image = await intercom_device.async_get_snapshot()
            except PikIntercomException as error:
                _LOGGER.error(log_prefix + f"Ошибка получения снимка: {error}")
            else:
                return snapshot_image

        # Attempt to retrieve snapshot image using RTSP stream
        stream_url = intercom_device.stream_url
        if stream_url:
            snapshot_image = await self.async_get_snapshot_by_ffmpeg(width, height)

            if not snapshot_image:
                _LOGGER.warning(log_prefix + "Видеопоток не содержит изображение")
                return None

            return snapshot_image

        # Warn about missing sources
        _LOGGER.warning(log_prefix + "Отсутствует источник снимков")
        return None

    async def stream_source(self) -> Optional[str]:
        """Return the RTSP stream source."""
        return self._intercom_device.stream_url
