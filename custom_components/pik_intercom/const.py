from typing import Final

DOMAIN: Final = "pik_intercom"
DATA_YAML_CONFIG: Final = DOMAIN + "_yaml_config"
DATA_ENTITIES: Final = DOMAIN + "_entities"
DATA_FINAL_CONFIG: Final = DOMAIN + "_final_config"
DATA_UPDATE_LISTENERS: Final = DOMAIN + "_update_listeners"
DATA_REAUTHENTICATORS: Final = DOMAIN + "_reauthenticators"
SUPPORTED_PLATFORMS: Final = ("camera", "switch", "sensor")
CONF_RETRIEVAL_ERROR_THRESHOLD: Final = "retrieval_error_threshold"
CONF_REAUTH_INTERVAL: Final = "reauth_interval"
CONF_CLIENT_APP: Final = "client_app"
CONF_CLIENT_OS: Final = "client_os"
CONF_CLIENT_VERSION: Final = "client_version"
CONF_USER_AGENT: Final = "user_agent"
