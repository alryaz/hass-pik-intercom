from typing import Final

DOMAIN: Final = "pik_intercom"
DATA_YAML_CONFIG: Final = DOMAIN + "_yaml_config"
DATA_ENTITIES: Final = DOMAIN + "_entities"
DATA_FINAL_CONFIG: Final = DOMAIN + "_final_config"
DATA_UPDATE_LISTENERS: Final = DOMAIN + "_update_listeners"
DATA_ENTITY_UPDATERS: Final = DOMAIN + "_entity_updaters"
DATA_REAUTHENTICATORS: Final = DOMAIN + "_reauthenticators"
SUPPORTED_PLATFORMS: Final = ("camera", "switch", "sensor")
CONF_REAUTH_INTERVAL: Final = "reauth_interval"
CONF_CLIENT_APP: Final = "client_app"
CONF_CLIENT_OS: Final = "client_os"
CONF_CLIENT_VERSION: Final = "client_version"
CONF_USER_AGENT: Final = "user_agent"
UPDATE_CONFIG_KEY_CALL_SESSIONS: Final = "call_sessions"
UPDATE_CONFIG_KEY_INTERCOMS: Final = "intercoms"
CONF_INTERCOMS_UPDATE_INTERVAL: Final = "intercoms_update_interval"
CONF_CALL_SESSIONS_UPDATE_INTERVAL: Final = "call_sessions_update_interval"
CONF_AUTH_UPDATE_INTERVAL: Final = "auth_update_interval"
DEFAULT_INTERCOMS_UPDATE_INTERVAL: Final = 60 * 60  # 1 hour
DEFAULT_CALL_SESSIONS_UPDATE_INTERVAL: Final = 10 * 60  # 10 minutes
DEFAULT_AUTH_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day
MIN_INTERCOMS_UPDATE_INTERVAL: Final = 5 * 60  # 5 minutes
MIN_CALL_SESSIONS_UPDATE_INTERVAL: Final = 30  # 30 seconds
MIN_AUTH_UPDATE_INTERVAL: Final = 2 * 60 * 60  # 2 hours
MIN_DEVICE_ID_LENGTH: Final = 6
