from typing import Final

DOMAIN: Final = "pik_intercom"

MANUFACTURER: Final = "PIK Group"

DATA_REAUTHENTICATORS: Final = DOMAIN + "_reauthenticators"
UPDATE_CONFIG_KEY_CALL_SESSIONS: Final = "call_sessions"
UPDATE_CONFIG_KEY_INTERCOMS: Final = "intercoms"
CONF_INTERCOMS_UPDATE_INTERVAL: Final = "intercoms_update_interval"
CONF_CALL_SESSIONS_UPDATE_INTERVAL: Final = "call_sessions_update_interval"
CONF_AUTH_UPDATE_INTERVAL: Final = "auth_update_interval"
DEFAULT_INTERCOMS_UPDATE_INTERVAL: Final = 60 * 60  # 1 hour
DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL: Final = 10 * 60  # 10 minutes
DEFAULT_AUTH_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day
MIN_INTERCOMS_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_CALL_SESSIONS_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_AUTH_UPDATE_INTERVAL: Final = 2 * 60 * 60  # 2 hours
MIN_DEVICE_ID_LENGTH: Final = 6
