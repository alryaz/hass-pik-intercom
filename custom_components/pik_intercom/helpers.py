import logging
import re
from functools import partial
from typing import (
    Type,
    Iterable,
    Mapping,
    Hashable,
    TypeVar,
    Callable,
    Sequence,
)

import voluptuous as vol
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from custom_components.pik_intercom.entity import (
    BasePikIntercomEntity,
    BasePikUpdateCoordinator,
)
from pik_intercom import BaseObject

_LOGGER = logging.getLogger(__name__)

_RE_USERNAME_MASK = re.compile(r"^(\W*)(.).*(.)$")


def phone_validator(phone_number: str) -> str:
    phone_number = re.sub(r"\D", "", phone_number)

    if len(phone_number) == 10:
        return "+7" + phone_number

    elif len(phone_number) == 11:
        if phone_number.startswith("8"):
            return "+7" + phone_number[1:]
        elif phone_number.startswith("7"):
            return "+" + phone_number
        else:
            raise vol.Invalid("Unknown phone number format detected")
    else:
        raise vol.Invalid(
            f"Irregular phone number length (expected 11, got {len(phone_number)})"
        )


def patch_haffmpeg():
    """Patch HA ffmpeg adapter to put rtsp_transport before input stream when
    a certain non-existent command line argument (input_rtsp_transport) is provided.

    """

    try:
        from haffmpeg.core import HAFFmpeg
    except (ImportError, FileNotFoundError):
        _LOGGER.warning(
            "haffmpeg could not be patched because it is not yet installed"
        )
        return

    if hasattr(HAFFmpeg, "_orig_generate_ffmpeg_cmd"):
        return

    HAFFmpeg._orig_generate_ffmpeg_cmd = HAFFmpeg._generate_ffmpeg_cmd

    def _generate_ffmpeg_cmd(self, *args, **kwargs) -> None:
        """Generate ffmpeg command line (patched to support input_rtsp_transport argument)."""
        self._orig_generate_ffmpeg_cmd(*args, **kwargs)

        _argv = self._argv
        try:
            rtsp_flags_index = _argv.index("-prefix_rtsp_flags")
        except ValueError:
            return
        try:
            rtsp_transport_spec = _argv[rtsp_flags_index + 1]
        except IndexError:
            return
        else:
            if not rtsp_transport_spec.startswith("-"):
                del _argv[rtsp_flags_index : rtsp_flags_index + 2]
                _argv.insert(1, "-rtsp_flags")
                _argv.insert(2, rtsp_transport_spec)

    HAFFmpeg._generate_ffmpeg_cmd = _generate_ffmpeg_cmd


_TBaseObject = TypeVar("_TBaseObject", bound=BaseObject)
_TUpdateCoordinator = TypeVar(
    "_TUpdateCoordinator", bound=BasePikUpdateCoordinator
)

EntityClassType = Type[
    BasePikIntercomEntity[_TUpdateCoordinator, _TBaseObject]
]
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
    logger: logging.Logger = _LOGGER,
) -> None:
    entities = coordinator.get_entities_dict(entity_classes)
    eid = coordinator.config_entry.entry_id[-6:]
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
                )
                new_entities.append(entity)
        if added_device_ids:
            _LOGGER.debug(
                f"[{eid}] Adding {entity_class.__name__} {domain}s for {added_device_ids}"
            )

    if new_entities:
        logger.debug(
            f"[{eid}] Adding {len(new_entities)} new {domain} entities"
        )
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
    logger: logging.Logger = _LOGGER,
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
