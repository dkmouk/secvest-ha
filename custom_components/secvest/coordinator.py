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


@dataclass
class SecvestData:
    raw_mode: str | None
    human_mode: str | None
    zones: dict[str, dict[str, Any]]  # key -> {name, state}
    faults: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    open_zone_names: list[str]
    open_zones_csv: str
    open_zones_spoken: str
    available: bool
    last_error: str | None


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
            update_interval=timedelta(seconds=scan_interval_s),
        )
        self.api = api

        self._zone_name_map = zone_name_map or {}
        self._zones_interval = timedelta(seconds=zones_interval_s)
        self._zones_tick = int(self._zones_interval.total_seconds())

        # Circuit breaker
        self._consecutive_failures = 0
        self._breaker_until = 0.0
        self._breaker_threshold = max(1, int(breaker_threshold))
        self._breaker_cooldown = max(10, int(breaker_cooldown))
        self._last_error: str | None = None

    def _with_status(self, base: SecvestData, *, available: bool, last_error: str | None) -> SecvestData:
        """Return a copy of base data with updated availability/error info."""
        return SecvestData(
            raw_mode=base.raw_mode,
            human_mode=base.human_mode,
            zones=base.zones,
            faults=base.faults,
            outputs=base.outputs,
            open_zone_names=base.open_zone_names,
            open_zones_csv=base.open_zones_csv,
            open_zones_spoken=base.open_zones_spoken,
            available=available,
            last_error=last_error,
        )

    async def _async_update_data(self) -> SecvestData:
        now = time.time()

        # Circuit breaker active: do not hammer device
        if now < self._breaker_until:
            if self.data:
                return self._with_status(
                    self.data,
                    available=False,
                    last_error=self._last_error or "Circuit breaker active",
                )
            raise UpdateFailed("Circuit breaker active")

        try:
            # --- Always fetch mode ---
            raw_mode = await self.api.get_mode()
            human_mode = STATE_TRANSLATIONS.get(raw_mode, "Unbekannt")

            # --- Fetch zones less frequently ---
            # update_interval can be None theoretically, but in our case it is set
            interval_s = int(self.update_interval.total_seconds())  # type: ignore[union-attr]
            self._zones_tick += interval_s

            zones_payload: list[dict[str, Any]] | None = None
            faults_payload: list[dict[str, Any]] | None = None
            outputs_payload: list[dict[str, Any]] | None = None
            wireless_zones_payload: dict[int, dict[str, Any]] = {}
            if self._zones_tick >= int(self._zones_interval.total_seconds()):
                self._zones_tick = 0
                zones_payload = await self.api.get_zones()
                try:
                    wireless_zones_payload = await self.api.get_wireless_zones_status()
                except Exception as err:
                    _LOGGER.debug("Secvest optional wireless zones refresh failed: %r", err)
                try:
                    faults_payload = await self.api.get_faults()
                except Exception as err:
                    _LOGGER.debug("Secvest optional faults refresh failed: %r", err)
                try:
                    outputs_payload = await self.api.get_outputs()
                except Exception as err:
                    _LOGGER.debug("Secvest optional outputs refresh failed: %r", err)

            # Keep old zones if we didn't fetch new ones
            zones_dict: dict[str, dict[str, Any]] = {}
            if self.data and self.data.zones:
                zones_dict = dict(self.data.zones)

            faults = list(self.data.faults) if self.data else []
            outputs = list(self.data.outputs) if self.data else []

            if zones_payload is not None:
                zones_dict = {}
                for idx, z in enumerate(zones_payload):
                    name = z.get("name")
                    state = z.get("state")
                    if not isinstance(name, str) or not isinstance(state, str):
                        continue
                    key = normalize_name(name)
                    zone_data = dict(z)
                    zone_data["name"] = name
                    zone_data["state"] = state
                    zone_data.update(wireless_zones_payload.get(idx, {}))
                    zones_dict[key] = zone_data

            if faults_payload is not None:
                faults = faults_payload

            if outputs_payload is not None:
                outputs = outputs_payload

            open_zone_names: list[str] = []
            for key, z in zones_dict.items():
                if z.get("state") == "open":
                    friendly = (
                        self._zone_name_map.get(key)
                        or self._zone_name_map.get(z.get("name", ""))  # optional
                    )
                    if not friendly:
                        friendly = key.replace("_", " ")
                    open_zone_names.append(friendly)

            open_zones_csv = ", ".join(open_zone_names)
            spoken = make_spoken_zone_list(open_zone_names)

            # Success: reset breaker
            self._consecutive_failures = 0
            self._breaker_until = 0.0
            self._last_error = None

            return SecvestData(
                raw_mode=raw_mode,
                human_mode=human_mode,
                zones=zones_dict,
                faults=faults,
                outputs=outputs,
                open_zone_names=open_zone_names,
                open_zones_csv=open_zones_csv,
                open_zones_spoken=spoken,
                available=True,
                last_error=None,
            )

        except (asyncio.TimeoutError, SecvestApiError) as err:
            # Temporary error: keep last state, but mark unavailable
            self._consecutive_failures += 1
            self._last_error = repr(err)

            if self._consecutive_failures >= self._breaker_threshold:
                self._breaker_until = time.time() + self._breaker_cooldown
                _LOGGER.warning(
                    "Secvest circuit breaker activated for %ss after %s consecutive failures. last_error=%s",
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
                return self._with_status(self.data, available=False, last_error=self._last_error)

            raise UpdateFailed(self._last_error or "Update failed")

        except Exception as err:
            # Unknown hard error: log and keep last data if possible
            self._consecutive_failures += 1
            self._last_error = repr(err)
            _LOGGER.exception("Secvest update failed (unexpected): %s", self._last_error)

            if self._consecutive_failures >= self._breaker_threshold:
                self._breaker_until = time.time() + self._breaker_cooldown

            if self.data:
                return self._with_status(self.data, available=False, last_error=self._last_error)

            raise UpdateFailed(self._last_error or "Update failed")
