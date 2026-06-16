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

LOGGER_NAME = "custom_components.secvest"

DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 10  # Sekunden (Mode)
DEFAULT_ZONES_INTERVAL = 10  # Sekunden (Zonen/Melder)
DEFAULT_RETRIES = 4
DEFAULT_BREAKER_THRESHOLD = 5      # nach 5 Fehlversuchen -> Pause
DEFAULT_BREAKER_COOLDOWN = 300      # Sekunden (5 Minuten)

SERVICE_SET_MODE = "secvest_set_mode"

MODE_SET = "set"
MODE_PARTSET = "partset"
MODE_UNSET = "unset"
VALID_MODES = {MODE_SET, MODE_PARTSET, MODE_UNSET}

STATE_TRANSLATIONS = {
    MODE_SET: "Scharf",
    MODE_PARTSET: "Teilscharf",
    MODE_UNSET: "Unscharf",
}
