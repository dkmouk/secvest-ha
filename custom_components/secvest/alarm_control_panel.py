from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SecvestApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities([SecvestAlarm(coordinator, entry)], True)


class SecvestAlarm(AlarmControlPanelEntity):
    """Alarm control panel for ABUS Secvest."""

    _attr_name = "Secvest Alarm"
    _attr_icon = "mdi:shield-home"

    # PIN/User-Code wird backendseitig gesendet -> kein UI-Code-Dialog
    _attr_code_arm_required = False
    _attr_code_disarm_required = False

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_alarm"

    @property
    def state(self) -> AlarmControlPanelState | None:
        d = self.coordinator.data
        if not d:
            return None
        if d.raw_mode == "unset":
            return AlarmControlPanelState.DISARMED
        if d.raw_mode == "partset":
            return AlarmControlPanelState.ARMED_HOME
        if d.raw_mode == "set":
            return AlarmControlPanelState.ARMED_AWAY
        return None

    async def async_arm_home(self, code: str | None = None) -> None:
        await self._arm_with_live_zone_refresh("partset")

    async def async_arm_away(self, code: str | None = None) -> None:
        await self._arm_with_live_zone_refresh("set")

    async def async_disarm(self, code: str | None = None) -> None:
        await self._set_mode("unset")

    # Old-style sync wrappers (HA may call these)
    def alarm_arm_home(self, code: str | None = None) -> None:
        fut = asyncio.run_coroutine_threadsafe(self.async_arm_home(code), self.hass.loop)
        return fut.result()

    def alarm_arm_away(self, code: str | None = None) -> None:
        fut = asyncio.run_coroutine_threadsafe(self.async_arm_away(code), self.hass.loop)
        return fut.result()

    def alarm_disarm(self, code: str | None = None) -> None:
        fut = asyncio.run_coroutine_threadsafe(self.async_disarm(code), self.hass.loop)
        return fut.result()

    async def _arm_with_live_zone_refresh(self, mode: str) -> None:
        """Refresh zones live (may take longer), then arm if everything is closed."""
        try:
            await self.coordinator.async_refresh_zones_now()
        except Exception as err:
            _LOGGER.warning("Live zones refresh failed before arming: %r", err)

        d = self.coordinator.data
        if d and d.open_zone_names:
            raise HomeAssistantError(d.open_zones_spoken or ("Offene Zonen: " + ", ".join(d.open_zone_names)))

        await self._set_mode(mode)

    async def _set_mode(self, mode: str) -> None:
        try:
            await self.coordinator.api.set_mode(mode)
            await self.coordinator.async_request_refresh()

        except asyncio.TimeoutError:
            raise HomeAssistantError("Secvest antwortet nicht (Timeout). Bitte erneut versuchen.")

        except SecvestApiError as err:
            raise HomeAssistantError(f"Secvest API Fehler: {err}") from err

        except aiohttp.ClientResponseError as err:
            raise HomeAssistantError(f"Secvest HTTP Fehler: {err.status}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error while setting Secvest mode to %s", mode)
            raise HomeAssistantError(f"Unbekannter Fehler: {err!r}") from err

    async def async_added_to_hass(self) -> None:
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.async_remove_listener(self.async_write_ha_state)
