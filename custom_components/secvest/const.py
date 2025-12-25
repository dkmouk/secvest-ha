DOMAIN = "secvest"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_USER_CODE = "user_code"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

CONF_ZONES_INTERVAL = "zones_interval"
CONF_RETRIES = "retries"
CONF_BREAKER_THRESHOLD = "breaker_threshold"
CONF_BREAKER_COOLDOWN = "breaker_cooldown"

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_ZONES_INTERVAL = 120

DEFAULT_RETRIES = 4
DEFAULT_BREAKER_THRESHOLD = 5
DEFAULT_BREAKER_COOLDOWN = 300

STATE_TRANSLATIONS = {
    "set": "Scharf",
    "partset": "Teilscharf",
    "unset": "Unscharf",
}

SERVICE_SET_MODE = "set_mode"
VALID_MODES = {"set", "partset", "unset"}
