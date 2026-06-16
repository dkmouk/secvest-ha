from __future__ import annotations

import asyncio
import logging
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SecvestApi, SecvestAuth, SecvestApiError
from .coordinator import SecvestCoordinator
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_USER_CODE,
    CONF_VERIFY_SSL,
    CONF_SCAN_INTERVAL,
    CONF_ZONES_INTERVAL,
    CONF_RETRIES,
    CONF_BREAKER_THRESHOLD,
    CONF_BREAKER_COOLDOWN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ZONES_INTERVAL,
    DEFAULT_RETRIES,
    DEFAULT_BREAKER_THRESHOLD,
    DEFAULT_BREAKER_COOLDOWN,
    SERVICE_SET_MODE,
    VALID_MODES,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["alarm_control_panel", "sensor", "binary_sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Secvest from a config entry."""
    session = async_get_clientsession(hass)

    # --- Read options (with sane defaults) ---
    options = entry.options
    scan_interval = options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    zones_interval = options.get(CONF_ZONES_INTERVAL, entry.data.get(CONF_ZONES_INTERVAL, DEFAULT_ZONES_INTERVAL))
    retries = options.get(CONF_RETRIES, DEFAULT_RETRIES)
    breaker_threshold = options.get(CONF_BREAKER_THRESHOLD, DEFAULT_BREAKER_THRESHOLD)
    breaker_cooldown = options.get(CONF_BREAKER_COOLDOWN, DEFAULT_BREAKER_COOLDOWN)

    # --- Auth ---
    auth = SecvestAuth(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        user_code=entry.data[CONF_USER_CODE],
    )

    # --- API ---
    api = SecvestApi(
        session=session,
        host=entry.data[CONF_HOST],
        auth=auth,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, False),
        retries=retries,
    )

    # --- Coordinator ---
    coordinator = SecvestCoordinator(
        hass=hass,
        api=api,
        scan_interval_s=scan_interval,
        zones_interval_s=zones_interval,
        breaker_threshold=breaker_threshold,
        breaker_cooldown=breaker_cooldown,
        zone_name_map=options.get("zone_name_map", {}),
    )

    # --- First refresh: FAIL-SOFT ---
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning(
            "Secvest first refresh failed, continuing setup anyway: %r",
            err,
            exc_info=True,
        )

    # --- Store runtime objects ---
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "entry": entry,
    }

    # --- Register service: secvest_set_mode ---
    async def handle_set_mode(call: ServiceCall) -> None:
        mode = call.data.get("mode")

        if mode not in VALID_MODES:
            raise HomeAssistantError(
                f"Invalid mode: {mode}. Use one of {sorted(VALID_MODES)}"
            )

        # Refresh before switching (check open zones)
        await coordinator.async_request_refresh()

        if not coordinator.data:
            raise HomeAssistantError("Secvest status currently unknown.")

        if mode in ("set", "partset") and coordinator.data.open_zone_names:
            raise HomeAssistantError(
                coordinator.data.open_zones_spoken
                or "Offene Zonen verhindern Aktivierung."
            )

        try:
            await api.set_mode(mode)

        except asyncio.TimeoutError:
            raise HomeAssistantError(
                "Secvest antwortet nicht (Timeout). Bitte später erneut versuchen."
            )

        except SecvestApiError as err:
            raise HomeAssistantError(f"Secvest API Fehler: {err}") from err

        except aiohttp.ClientResponseError as err:
            raise HomeAssistantError(f"Secvest HTTP Fehler: {err.status}") from err

        # Refresh after switching
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MODE,
        handle_set_mode,
    )

    # --- Forward platforms ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Secvest config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SET_MODE)

    return unload_ok
