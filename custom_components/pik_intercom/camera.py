"""This component provides basic support for Pik Domofon IP intercoms."""
import asyncio
import logging
from typing import Optional

from homeassistant.components.camera import Camera, SUPPORT_STREAM
from homeassistant.helpers.typing import HomeAssistantType

from custom_components.pik_intercom.api import PikDomofonAPI, PikDomofonIntercom
from custom_components.pik_intercom import DATA_ENTITIES, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistantType, config_entry, async_add_entities
) -> bool:
    """Add a Dahua IP camera from a config entry."""

    api: PikDomofonAPI = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        [
            PikDomofonCamera(intercom_object)
            for intercom_object in api.intercoms.values()
            if intercom_object.has_camera
        ]
    )

    return True


class PikDomofonCamera(Camera):
    """An implementation of a Pik Domofon IP intercom."""

    def __init__(self, intercom_object: PikDomofonIntercom) -> None:
        """Initialize the Pik Domofon intercom video stream."""
        super().__init__()

        self.entity_id = f"switch.{intercom_object.id}_camera"

        self._intercom_object = intercom_object

    async def async_added_to_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].setdefault(
            self.registry_entry.config_entry_id, []
        ).append(self)

    async def async_will_remove_from_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].get(
            self.registry_entry.config_entry_id, []
        ).remove(self)

    def turn_off(self) -> None:
        raise NotImplementedError

    def turn_on(self) -> None:
        raise NotImplementedError

    def enable_motion_detection(self) -> None:
        raise NotImplementedError

    def disable_motion_detection(self) -> None:
        raise NotImplementedError

    @property
    def icon(self) -> str:
        return "mdi:doorbell-video"

    @property
    def unique_id(self):
        """Return the entity unique ID."""
        intercom_object = self._intercom_object
        return f"intercom_camera_{intercom_object.property_id}_{intercom_object.id}"

    def camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        return asyncio.run_coroutine_threadsafe(
            self.async_camera_image(width, height),
            self.hass.loop,
        ).result()

    async def async_camera_image(
        self, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        """Return a still image response from the camera."""
        # Send the request to snap a picture and return raw jpg data
        return await self._intercom_object.async_get_snapshot()

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return SUPPORT_STREAM

    async def stream_source(self) -> Optional[str]:
        """Return the RTSP stream source."""
        return self._intercom_object.stream_url

    @property
    def motion_detection_enabled(self) -> bool:
        """Camera Motion Detection Status."""
        return False

    @property
    def name(self):
        """Return the name of this camera."""
        intercom_object = self._intercom_object
        return (
            intercom_object.renamed_name
            or intercom_object.human_name
            or intercom_object.name
        )
