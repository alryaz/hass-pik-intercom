import logging
import re

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


_RE_USERNAME_MASK = re.compile(r"^(\W*)(.).*(.)$")


def mask_username(username: str):
    parts = username.split("@")
    return "@".join(map(lambda x: _RE_USERNAME_MASK.sub(r"\1\2***\3", x), parts))


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
        raise vol.Invalid(f"Irregular phone number length (expected 11, got {len(phone_number)})")


def patch_haffmpeg():
    """Patch HA ffmpeg adapter to put rtsp_transport before input stream when
    a certain non-existent command line argument (input_rtsp_transport) is provided.

    """

    try:
        from haffmpeg.core import HAFFmpeg
    except (ImportError, FileNotFoundError):
        _LOGGER.warning("haffmpeg could not be patched because it is not yet installed")
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
