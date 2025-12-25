from __future__ import annotations

import asyncio
import logging
import socket
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry

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
)

_LOGGER = logging.getLogger(__name__)


class SecvestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_USER_CODE): str,
                vol.Optional(CONF_VERIFY_SSL, default=False): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        try:
            host_input = user_input[CONF_HOST].strip()
            parsed = urlparse(host_input if "://" in host_input else f"https://{host_input}")
            hostname = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            if not hostname:
                errors["base"] = "cannot_connect"
            else:
                await self._async_test_tcp_socket(hostname, port, timeout=20, retries=3)

        except Exception as e:
            _LOGGER.warning("Secvest config_flow TCP test failed: %s", e, exc_info=True)
            errors["base"] = "cannot_connect"

        if errors:
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        await self.async_set_unique_id(user_input[CONF_HOST])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Secvest ({user_input[CONF_HOST]})",
            data=user_input,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry):
        return SecvestOptionsFlowHandler(config_entry)

    async def _async_test_tcp_socket(self, host: str, port: int, timeout: int = 20, retries: int = 3) -> None:
        last_exc: Exception | None = None

        def _connect_blocking():
            with socket.create_connection((host, port), timeout=timeout):
                return True

        for attempt in range(1, retries + 1):
            try:
                await self.hass.async_add_executor_job(_connect_blocking)
                return
            except Exception as e:
                last_exc = e
                _LOGGER.warning("Secvest TCP test attempt %s/%s failed: %s", attempt, retries, e)
                await asyncio.sleep(1.0)

        raise last_exc or TimeoutError("TCP connect failed")


class SecvestOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: ConfigEntry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
                vol.Optional(CONF_ZONES_INTERVAL, default=opts.get(CONF_ZONES_INTERVAL, DEFAULT_ZONES_INTERVAL)): int,
                vol.Optional(CONF_RETRIES, default=opts.get(CONF_RETRIES, DEFAULT_RETRIES)): int,
                vol.Optional(CONF_BREAKER_THRESHOLD, default=opts.get(CONF_BREAKER_THRESHOLD, DEFAULT_BREAKER_THRESHOLD)): int,
                vol.Optional(CONF_BREAKER_COOLDOWN, default=opts.get(CONF_BREAKER_COOLDOWN, DEFAULT_BREAKER_COOLDOWN)): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
