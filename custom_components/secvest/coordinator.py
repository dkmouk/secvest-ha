from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SecvestApi, SecvestApiError
from .const import DEFAULT_ZONES_INTERVAL, STATE_TRANSLATIONS

_LOGGER = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    return (
        name.replace(".", "_")
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("ä", "ae")
        .replace("Ä", "ae")
        .replace("ö", "oe")
        .replace("Ö", "oe")
        .replace("ü", "ue")
        .replace("Ü", "ue")
        .replace("ß", "ss")
    )


def make_spoken_zone_list(zones: list[str]) -> str:
    if not zones:
        return ""
    if len(zones) == 1:
        return f"Ich konnte die Alarmanlage nicht aktivieren, bitte schließe: {zones[0]}."
    last = zones[-1]
    head = ", ".join(zones[:-1])
    return (
        "Ich konnte die Alarmanlage nicht aktivieren, bitte folgende Fenster und Türen schließen: "
        f"{head} und {last}."
    )


def build_zones_dict(
    zones_payload: list[dict[str, Any]],
    zone_name_map: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build normalized zones dict and enrich with friendly_name (single source of truth)."""
    zone_name_map = zone_name_map or {}
    out: dict[str, dict[str, Any]] = {}

    for z in zones_payload:
        if not isinstance(z, dict):
            continue
        raw_name = z.get("name")
        state = z.get("state")
        if not isinstance(raw_name, str) or not isinstance(state, str):
            continue

        key = normalize_name(raw_name)
        friendly = zone_name_map.get(key) or zone_name_map.get(raw_name)
        if not friendly:
            friendly = key.replace("_", " ")

        out[key] = {
            "name": raw_name,
            "friendly_name": friendly,
            "state": state,
        }

    return out


@dataclass
class SecvestData:
    raw_mode: str | None
    human_mode: str | None
    zones: dict[str, dict[str, Any]]
    open_zone_names: list[str]
    open_zones_csv: str
    open_zones_spoken: str
    available: bool
    last_error: str | None


class SecvestCoordinator(DataUpdateCoordinator[SecvestData]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: SecvestApi,
        scan_interval_s: int,
        zone_name_map: dict[str, str] | None = None,
        zones_interval_s: int = DEFAULT_ZONES_INTERVAL,
        breaker_threshold: int = 5,
        breaker_cooldown: int = 300,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Secvest Coordinator",
            update_interval=timedelta(seconds=int(scan_interval_s)),
        )

        self.api = api
        self.zone_name_map: dict[str, str] = zone_name_map or {}

        self._zones_interval = timedelta(seconds=int(zones_interval_s))
        self._zones_tick = 0

        self._consecutive_failures = 0
        self._breaker_until = 0.0
        self._breaker_threshold = max(1, int(breaker_threshold))
        self._breaker_cooldown = max(10, int(breaker_cooldown))
        self._last_error: str | None = None

    def _compose_data(
        self,
        *,
        raw_mode: str | None,
        human_mode: str | None,
        zones: dict[str, dict[str, Any]],
        available: bool,
        last_error: str | None,
    ) -> SecvestData:
        open_zone_names = [
            z["friendly_name"]
            for z in zones.values()
            if isinstance(z, dict) and z.get("state") == "open" and isinstance(z.get("friendly_name"), str)
        ]
        open_zones_csv = ", ".join(open_zone_names)
        open_zones_spoken = make_spoken_zone_list(open_zone_names)

        return SecvestData(
            raw_mode=raw_mode,
            human_mode=human_mode,
            zones=zones,
            open_zone_names=open_zone_names,
            open_zones_csv=open_zones_csv,
            open_zones_spoken=open_zones_spoken,
            available=available,
            last_error=last_error,
        )

    async def async_refresh_zones_now(self) -> None:
        """Force a live zones refresh and publish data immediately (prevents stale zone status)."""
        zones_payload = await self.api.get_zones()
        zones_dict = build_zones_dict(zones_payload, self.zone_name_map)

        d = self.data
        if d:
            new_data = self._compose_data(
                raw_mode=d.raw_mode,
                human_mode=d.human_mode,
                zones=zones_dict,
                available=True,
                last_error=d.last_error,
            )
        else:
            new_data = self._compose_data(
                raw_mode=None,
                human_mode=None,
                zones=zones_dict,
                available=True,
                last_error=None,
            )

        self._last_error = None
        self._consecutive_failures = 0
        self._breaker_until = 0.0
        self.async_set_updated_data(new_data)

    async def _async_update_data(self) -> SecvestData:
        now = time.time()
        if now < self._breaker_until:
            if self.data:
                return self._compose_data(
                    raw_mode=self.data.raw_mode,
                    human_mode=self.data.human_mode,
                    zones=self.data.zones,
                    available=False,
                    last_error=self._last_error or "Circuit breaker active",
                )
            raise UpdateFailed("Circuit breaker active")

        try:
            raw_mode = await self.api.get_mode()
            human_mode = STATE_TRANSLATIONS.get(raw_mode, "Unbekannt")

            interval_s = int(self.update_interval.total_seconds())  # type: ignore[union-attr]
            self._zones_tick += interval_s

            zones_dict: dict[str, dict[str, Any]] = {}
            if self.data and self.data.zones:
                zones_dict = dict(self.data.zones)

            if self._zones_tick >= int(self._zones_interval.total_seconds()):
                self._zones_tick = 0
                zones_payload = await self.api.get_zones()
                zones_dict = build_zones_dict(zones_payload, self.zone_name_map)

            self._consecutive_failures = 0
            self._breaker_until = 0.0
            self._last_error = None

            return self._compose_data(
                raw_mode=raw_mode,
                human_mode=human_mode,
                zones=zones_dict,
                available=True,
                last_error=None,
            )

        except (asyncio.TimeoutError, SecvestApiError) as err:
            self._consecutive_failures += 1
            self._last_error = repr(err)

            if self._consecutive_failures >= self._breaker_threshold:
                self._breaker_until = time.time() + self._breaker_cooldown
                _LOGGER.warning(
                    "Secvest circuit breaker activated for %ss after %s failures. last_error=%s",
                    self._breaker_cooldown,
                    self._consecutive_failures,
                    self._last_error,
                )
            else:
                _LOGGER.warning(
                    "Secvest temporary error (%s/%s): %s",
                    self._consecutive_failures,
                    self._breaker_threshold,
                    self._last_error,
                )

            if self.data:
                return self._compose_data(
                    raw_mode=self.data.raw_mode,
                    human_mode=self.data.human_mode,
                    zones=self.data.zones,
                    available=False,
                    last_error=self._last_error,
                )
            raise UpdateFailed(self._last_error or "Update failed") from err

        except Exception as err:
            self._consecutive_failures += 1
            self._last_error = repr(err)
            _LOGGER.exception("Secvest update failed (unexpected): %s", self._last_error)

            if self._consecutive_failures >= self._breaker_threshold:
                self._breaker_until = time.time() + self._breaker_cooldown

            if self.data:
                return self._compose_data(
                    raw_mode=self.data.raw_mode,
                    human_mode=self.data.human_mode,
                    zones=self.data.zones,
                    available=False,
                    last_error=self._last_error,
                )
            raise UpdateFailed(self._last_error or "Update failed") from err
