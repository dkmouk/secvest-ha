from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEVICE_TOKEN_RE = re.compile(r"^([A-Z0-9]{4,})\b")


def _faults(data: Any) -> list[dict[str, Any]]:
    faults = getattr(data, "faults", None)
    if isinstance(faults, list):
        return [item for item in faults if isinstance(item, dict)]
    return []


def _is_battery_fault(fault: dict[str, Any]) -> bool:
    text = str(fault.get("ui-string") or fault.get("text") or fault.get("name") or "").lower()
    fault_type = str(fault.get("type") or "").strip()
    return "batt" in text or "battery" in text or "akku" in text or fault_type in {"830"}


def _fault_device_token(fault: dict[str, Any]) -> str | None:
    text = str(fault.get("ui-string") or fault.get("text") or fault.get("name") or "").strip().upper()
    match = DEVICE_TOKEN_RE.match(text)
    return match.group(1) if match else None


def _fault_text(fault: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("ui-string", "text", "name", "desc", "description", "message"):
        value = fault.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts)


def _fault_type(fault: dict[str, Any]) -> str:
    return str(fault.get("type") or fault.get("fault-type") or fault.get("fault_type") or "").strip()


def _as_text_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return {str(value).strip().lower()} if str(value).strip() else set()


def _zone_ids(zone: dict[str, Any], zone_key: str) -> set[str]:
    ids = {zone_key.lower()}
    for key in ("id", "zone", "zone-id", "zone_id", "number", "no"):
        value = zone.get(key)
        if value is not None and str(value).strip():
            ids.add(str(value).strip().lower())
    return ids


def _fault_zone_ids(fault: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in (
        "zone",
        "zones",
        "zone-id",
        "zone_id",
        "zone-number",
        "zone_number",
        "affects-zone",
        "affects-zones",
        "affects_zone",
        "affects_zones",
        "source-zone",
        "source_zone",
    ):
        ids.update(_as_text_set(fault.get(key)))
    return ids


def _fault_matches_zone(fault: dict[str, Any], zone: dict[str, Any], zone_key: str) -> bool:
    fault_zone_ids = _fault_zone_ids(fault)
    zone_ids = _zone_ids(zone, zone_key)
    if fault_zone_ids and fault_zone_ids.intersection(zone_ids):
        return True

    text = _fault_text(fault).lower()
    if not text:
        return False

    zone_name = str(zone.get("name") or "").strip().lower()
    if zone_name and zone_name in text:
        return True

    for zone_id in zone_ids:
        if zone_id and re.search(rf"\b{re.escape(zone_id)}\b", text):
            return True

    token = _fault_device_token(fault)
    return bool(token and token.lower() in zone_ids)


def _zone_faults(data: Any, zone: dict[str, Any], zone_key: str) -> list[dict[str, Any]]:
    return [
        fault
        for fault in _faults(data)
        if _fault_matches_zone(fault, zone, zone_key)
    ]


def _is_rf_fault(fault: dict[str, Any]) -> bool:
    text = _fault_text(fault).lower()
    if bool(fault.get("is-rf-warning")):
        return True
    return "rf" in text or "funk" in text or "supervision" in text


def _is_sabotage_fault(fault: dict[str, Any]) -> bool:
    text = _fault_text(fault).lower()
    return _fault_type(fault) == "5010" or "sabotage" in text or "tamper" in text


def _fault_labels(faults: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for fault in faults:
        text = _fault_text(fault).strip()
        if text:
            labels.append(text)
        else:
            labels.append(str(fault))
    return labels


def _zone_name(zone: dict[str, Any], fallback: str) -> str:
    name = zone.get("name")
    return name if isinstance(name, str) and name.strip() else fallback.replace("_", " ")


def _zone_device_class(name: str) -> BinarySensorDeviceClass:
    upper = name.upper()
    if "GLAS" in upper or "GLASS" in upper:
        return BinarySensorDeviceClass.SAFETY
    if "TUR" in upper or "TUER" in upper or "TÜR" in upper or "DOOR" in upper:
        return BinarySensorDeviceClass.DOOR
    return BinarySensorDeviceClass.WINDOW


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
        SecvestAnyFaultBinarySensor(coordinator, entry),
        SecvestBatteryFaultBinarySensor(coordinator, entry),
    ]

    existing_zone_keys: set[str] = set()
    existing_battery_tokens: set[str] = set()

    if coordinator.data:
        for zone_key in coordinator.data.zones:
            existing_zone_keys.add(zone_key)
            entities.append(SecvestZoneBinarySensor(coordinator, entry, zone_key))

        for token in _battery_tokens(coordinator.data):
            existing_battery_tokens.add(token)
            entities.append(SecvestBatteryDeviceFaultBinarySensor(coordinator, entry, token))

    async_add_entities(entities, True)

    @callback
    def _maybe_add_new_entities() -> None:
        d = coordinator.data
        if not d:
            return

        new_entities: list[BinarySensorEntity] = []
        for zone_key in d.zones:
            if zone_key in existing_zone_keys:
                continue
            existing_zone_keys.add(zone_key)
            _LOGGER.info("Discovered new Secvest zone: %s", zone_key)
            new_entities.append(SecvestZoneBinarySensor(coordinator, entry, zone_key))

        for token in _battery_tokens(d):
            if token in existing_battery_tokens:
                continue
            existing_battery_tokens.add(token)
            _LOGGER.info("Discovered new Secvest battery fault device: %s", token)
            new_entities.append(SecvestBatteryDeviceFaultBinarySensor(coordinator, entry, token))

        if new_entities:
            async_add_entities(new_entities, True)

    coordinator.async_add_listener(_maybe_add_new_entities)


def _battery_tokens(data: Any) -> list[str]:
    tokens: set[str] = set()
    for fault in _faults(data):
        if not _is_battery_fault(fault):
            continue
        tokens.add(_fault_device_token(fault) or "UNKNOWN")
    return sorted(tokens)


class SecvestBaseEntity:
    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._remove_coordinator_listener = None

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
        self._remove_coordinator_listener = self.coordinator.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_coordinator_listener:
            self._remove_coordinator_listener()
            self._remove_coordinator_listener = None


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
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_any_zone_open"

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d and d.open_zone_names)


class SecvestAnyFaultBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_name = "Secvest Problem"
    _attr_icon = "mdi:alert-circle"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_fault_any"

    @property
    def is_on(self) -> bool:
        return bool(_faults(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        faults = _faults(self.coordinator.data)
        return {"count": len(faults), "items": faults}


class SecvestBatteryFaultBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_name = "Secvest Batterie Warnung"
    _attr_icon = "mdi:battery-alert"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_fault_battery"

    @property
    def is_on(self) -> bool:
        return any(_is_battery_fault(fault) for fault in _faults(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        faults = [fault for fault in _faults(self.coordinator.data) if _is_battery_fault(fault)]
        return {
            "count": len(faults),
            "items": [fault.get("ui-string") for fault in faults if fault.get("ui-string")],
        }


class SecvestBatteryDeviceFaultBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    _attr_icon = "mdi:battery-alert"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, token: str) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._token = token
        self._attr_unique_id = f"{entry.entry_id}_fault_battery_device_{token.lower()}"
        self._attr_name = f"Secvest Batterie {token}"

    def _my_faults(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for fault in _faults(self.coordinator.data):
            if not _is_battery_fault(fault):
                continue
            token = _fault_device_token(fault) or "UNKNOWN"
            if token == self._token:
                result.append(fault)
        return result

    @property
    def is_on(self) -> bool:
        return bool(self._my_faults())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        faults = self._my_faults()
        return {
            "device_token": self._token,
            "count": len(faults),
            "items": faults,
        }


class SecvestZoneBinarySensor(SecvestBaseEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, zone_key: str) -> None:
        SecvestBaseEntity.__init__(self, coordinator, entry)
        self._zone_key = zone_key
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_key}"

    def _zone(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        zone = d.zones.get(self._zone_key, {})
        return zone if isinstance(zone, dict) else {}

    @property
    def name(self) -> str:
        return f"Secvest {_zone_name(self._zone(), self._zone_key)}"

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        return _zone_device_class(_zone_name(self._zone(), self._zone_key))

    @property
    def icon(self) -> str | None:
        if self.device_class == BinarySensorDeviceClass.SAFETY:
            return "mdi:glass-fragile"
        return None

    @property
    def is_on(self) -> bool | None:
        zone = self._zone()
        if not zone:
            return None
        return str(zone.get("state", "")).lower() == "open"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone()
        faults = _zone_faults(self.coordinator.data, zone, self._zone_key)
        battery_faults = [fault for fault in faults if _is_battery_fault(fault)]
        rf_faults = [fault for fault in faults if _is_rf_fault(fault)]
        sabotage_faults = [fault for fault in faults if _is_sabotage_fault(fault)]
        return {
            "secvest_key": self._zone_key,
            "secvest_name": zone.get("name"),
            "secvest_state": zone.get("state"),
            "zone_id": zone.get("id") or zone.get("zone") or zone.get("zone-id") or zone.get("zone_id"),
            "zone_type": zone.get("type"),
            "inner": zone.get("inner"),
            "omittable": zone.get("omittable"),
            "omitted": zone.get("omitted"),
            "is_glassbreak": self.device_class == BinarySensorDeviceClass.SAFETY,
            "fault_count": len(faults),
            "faults": faults,
            "fault_labels": _fault_labels(faults),
            "battery_ok": not battery_faults,
            "battery_fault": bool(battery_faults),
            "battery_faults": battery_faults,
            "rf_ok": not rf_faults,
            "rf_fault": bool(rf_faults),
            "signal_ok": not rf_faults,
            "supervision_ok": not rf_faults,
            "rf_faults": rf_faults,
            "sabotage_ok": not sabotage_faults,
            "sabotage_fault": bool(sabotage_faults),
            "sabotage_faults": sabotage_faults,
        }
