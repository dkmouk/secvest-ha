from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    async_add_entities(
        [
            SecvestSimpleSensor(coordinator, entry, "Secvest Mode (Raw)", "raw_mode"),
            SecvestSimpleSensor(coordinator, entry, "Secvest Mode (DE)", "human_mode"),
            SecvestSimpleSensor(coordinator, entry, "Open Zones (CSV)", "open_zones_csv"),
            SecvestSimpleSensor(coordinator, entry, "Open Zones Spoken", "open_zones_spoken"),
            SecvestDerivedSensor(coordinator, entry, "Open Zones Count", "open_zones_count"),
            SecvestSimpleSensor(coordinator, entry, "Last Error", "last_error"),
        ],
        True,
    )


class SecvestBaseEntity:
    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="ABUS Secvest",
            manufacturer="ABUS",
            model="Secvest",
            configuration_url=self._entry.data.get("host"),
        )

    async def async_added_to_hass(self) -> None:
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.async_remove_listener(self.async_write_ha_state)


class SecvestSimpleSensor(SecvestBaseEntity, SensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, name: str, key: str) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_sensor_{key}"

    @property
    def native_value(self) -> Any:
        d = self.coordinator.data
        if not d:
            if self._key == "last_error":
                return "OK"
            return None

        val = getattr(d, self._key, None)

        if self._key == "last_error":
            return val or "OK"

        return val


class SecvestDerivedSensor(SecvestBaseEntity, SensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, name: str, key: str) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_sensor_{key}"

    @property
    def native_value(self) -> Any:
        d = self.coordinator.data
        if not d:
            if self._key == "open_zones_count":
                return 0
            return None

        if self._key == "open_zones_count":
            return len(d.open_zone_names) if d.open_zone_names else 0

        return None
