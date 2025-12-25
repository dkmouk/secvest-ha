from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    entities: list[BinarySensorEntity] = [
        SecvestAvailableBinarySensor(coordinator, entry),
        SecvestAnyZoneOpenBinarySensor(coordinator, entry),
    ]

    existing_zone_keys: set[str] = set()
    if coordinator.data and coordinator.data.zones:
        for zone_key in coordinator.data.zones.keys():
            existing_zone_keys.add(zone_key)
            entities.append(SecvestZoneBinarySensor(coordinator, entry, zone_key))

    async_add_entities(entities, True)

    @callback
    def _maybe_add_new_zone_entities() -> None:
        d = coordinator.data
        if not d or not d.zones:
            return

        new_entities: list[BinarySensorEntity] = []
        for zone_key in d.zones.keys():
            if zone_key in existing_zone_keys:
                continue
            existing_zone_keys.add(zone_key)
            _LOGGER.info("Discovered new Secvest zone: %s", zone_key)
            new_entities.append(SecvestZoneBinarySensor(coordinator, entry, zone_key))

        if new_entities:
            async_add_entities(new_entities, True)

    coordinator.async_add_listener(_maybe_add_new_zone_entities)


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


class SecvestAvailableBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_name = "Secvest Available"
    _attr_icon = "mdi:shield-check"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_available"

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d and d.available)


class SecvestAnyZoneOpenBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_name = "Secvest Any Zone Open"
    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_any_zone_open"

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d and d.open_zone_names)


class SecvestZoneBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator, entry: ConfigEntry, zone_key: str) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._zone_key = zone_key
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_key}"

    @property
    def name(self) -> str:
        d = self.coordinator.data
        if not d:
            return f"Secvest Zone {self._zone_key.replace('_', ' ')}"
        zone = d.zones.get(self._zone_key, {})
        friendly = zone.get("friendly_name")
        if isinstance(friendly, str) and friendly:
            return f"Secvest {friendly}"
        return f"Secvest Zone {self._zone_key.replace('_', ' ')}"

    @property
    def is_on(self) -> bool | None:
        d = self.coordinator.data
        if not d:
            return None
        zone = d.zones.get(self._zone_key)
        if not zone:
            return None
        return zone.get("state") == "open"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        zone = d.zones.get(self._zone_key, {})
        return {
            "secvest_key": self._zone_key,
            "secvest_name": zone.get("name"),
            "friendly_name": zone.get("friendly_name"),
            "secvest_state": zone.get("state"),
        }
