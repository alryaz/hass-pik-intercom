from typing import Final

DOMAIN: Final = "pik_intercom"

DATA_ENTITIES: Final = DOMAIN + "_entities"
DATA_REAUTHENTICATORS: Final = DOMAIN + "_reauthenticators"

MANUFACTURER: Final = "PIK Group"

CONF_INTERCOMS_UPDATE_INTERVAL: Final = "intercoms_update_interval"
CONF_AUTH_UPDATE_INTERVAL: Final = "auth_update_interval"
CONF_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = (
    "last_call_session_update_interval"
)
CONF_IOT_UPDATE_INTERVAL: Final = "iot_update_interval"
CONF_ICM_SEPARATE_UPDATES: Final = "icm_separate_updates"
CONF_ADD_SUGGESTED_AREAS: Final = "add_suggested_areas"

DEFAULT_INTERCOMS_UPDATE_INTERVAL: Final = 10 * 60  # 10 minutes
DEFAULT_AUTH_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day
DEFAULT_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = 7  # 7 seconds
DEFAULT_METERS_UPDATE_INTERVAL: Final = 24 * 60 * 60  # 1 day
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_ICM_SEPARATE_UPDATES: Final = False
DEFAULT_ADD_SUGGESTED_AREAS: Final = False

MIN_INTERCOMS_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_AUTH_UPDATE_INTERVAL: Final = 2 * 60 * 60  # 2 hours
MIN_LAST_CALL_SESSION_UPDATE_INTERVAL: Final = 3  # 2 seconds
MIN_IOT_UPDATE_INTERVAL: Final = 15  # 15 seconds
MIN_DEVICE_ID_LENGTH: Final = 6

ATTR_CALL_DURATION: Final = "call_duration"
ATTR_CALL_FROM: Final = "call_from"
ATTR_CALL_ID: Final = "call_id"
ATTR_GEO_UNIT_ID: Final = "geo_unit_id"
ATTR_GEO_UNIT_SHORT_NAME: Final = "geo_unit_short_name"
ATTR_HANGUP: Final = "hangup"
ATTR_IDENTIFIER: Final = "identifier"
ATTR_INTERCOM_ID: Final = "intercom_id"
ATTR_INTERCOM_NAME: Final = "intercom_name"
ATTR_KIND: Final = "kind"
ATTR_MODE: Final = "mode"
ATTR_PIPE_IDENTIFIER: Final = "pipe_identifier"
ATTR_PROPERTY_ID: Final = "property_id"
ATTR_PROPERTY_NAME: Final = "property_name"
ATTR_PROVIDER: Final = "provider"
ATTR_PROXY: Final = "proxy"
ATTR_SERIAL: Final = "serial"
ATTR_SESSION_ID: Final = "session_id"
ATTR_SIP_PROXY: Final = "sip_proxy"
ATTR_SNAPSHOT_URL: Final = "snapshot_url"
ATTR_TARGET_RELAY_IDS: Final = "target_relay_ids"
ATTR_TYPE: Final = "type"
