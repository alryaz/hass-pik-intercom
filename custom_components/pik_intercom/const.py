from typing import Final

DOMAIN: Final = "pik_intercom"

MANUFACTURER: Final = "PIK Group"

DATA_REAUTHENTICATORS: Final = DOMAIN + "_reauthenticators"

CONF_INTERCOMS_UPDATE_INTERVAL: Final = "intercoms_update_interval"
CONF_AUTH_UPDATE_INTERVAL: Final = "auth_update_interval"
CONF_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = "last_call_session_update_interval"
CONF_IOT_UPDATE_INTERVAL: Final = "iot_update_interval"

DEFAULT_INTERCOMS_UPDATE_INTERVAL: Final = 10 * 60  # 10 minutes
DEFAULT_AUTH_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day
DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = 7  # 7 seconds
DEFAULT_METERS_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day

MIN_INTERCOMS_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_AUTH_UPDATE_INTERVAL: Final = 2 * 60 * 60  # 2 hours
MIN_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = 3  # 2 seconds
MIN_IOT_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_DEVICE_ID_LENGTH: Final = 6
