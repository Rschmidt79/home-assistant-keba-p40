"""Config-entry-based, local KEBA KeContact P40 integration."""

from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import P40Api
from .const import CONF_FINGERPRINT, DEFAULT_PORT, DOMAIN
from .coordinator import P40Coordinator

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SWITCH,
]
type P40ConfigEntry = ConfigEntry[P40Coordinator]


_LOGGER = logging.getLogger(__name__)
LEGACY_ENTITY_KEYS = {
    "sensor": frozenset(
        {
            "state",
            "phase_used",
            "measured_active_phases",
            "current_offered",
            "total_active_power",
            "total_energy",
            "temperature",
            "current_l1",
            "current_l2",
            "current_l3",
            "voltage_l1",
            "voltage_l2",
            "voltage_l3",
            "hardware_max_current",
            "error_code",
            "max_asymmetrical_phase_current",
        }
    ),
    "binary_sensor": frozenset({"vehicle_connected", "session_active"}),
    "button": frozenset(
        {"increase_charging_power", "decrease_charging_power", "start_charging", "stop_charging"}
    ),
    "number": frozenset({"max_available_current"}),
    "select": frozenset({"phases", "target_charging_power"}),
}


@callback
def _async_remove_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Remove exact proven legacy IDs only after current entities exist.

    Friendly names, entity-ID suffixes and prefix matches are never evidence.
    Scope by config entry, platform and entity domain; unknown IDs survive.
    """
    from .binary_sensor import BINARY_SENSORS
    from .sensor import SENSORS

    serial = entry.unique_id
    if serial is None or not re.fullmatch(r"[0-9]+", serial):
        return 0
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    current = {
        (domain, f"{serial}_{description.key}")
        for domain, descriptions in (("sensor", SENSORS), ("binary_sensor", BINARY_SENSORS))
        for description in descriptions
    }
    present = {(entity.domain, entity.unique_id) for entity in entries if entity.platform == DOMAIN}
    if not current.issubset(present):
        return 0
    known = {
        (domain, f"{DOMAIN}_{serial}_{key}")
        for domain, keys in LEGACY_ENTITY_KEYS.items()
        for key in keys
    }
    removed = 0
    for entity in entries:
        if entity.platform == DOMAIN and (entity.domain, entity.unique_id) in known:
            registry.async_remove(entity.entity_id)
            removed += 1
    return removed


def make_api(hass: HomeAssistant, data: dict) -> P40Api:
    """Shared HA session; credentials never passed to logging or diagnostics."""
    if not data.get(CONF_PASSWORD):
        raise ConfigEntryAuthFailed("KEBA credentials must be re-entered")
    return P40Api(
        async_get_clientsession(hass),
        data[CONF_HOST],
        data.get(CONF_PORT, DEFAULT_PORT),
        data.get(CONF_USERNAME, "admin"),
        data[CONF_PASSWORD],
        verify_ssl=data.get(CONF_VERIFY_SSL, True),
        fingerprint=data.get(CONF_FINGERPRINT, ""),
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Adopt v1 entries, including the previous integration's implicit admin.

    Legacy options override data, as they did in the old integration. Consolidate
    them so later reconfiguration cannot be shadowed by old options. No network
    call, credential logging or entity/device identity change is involved.
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        data = {**entry.data, **entry.options}
        data.setdefault(CONF_USERNAME, "admin")
        hass.config_entries.async_update_entry(entry, data=data, options={}, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: P40ConfigEntry) -> bool:
    api = make_api(hass, entry.data)
    coordinator = P40Coordinator(hass, entry, api)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        api.close()
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(api.close)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        if removed := _async_remove_legacy_entities(hass, entry):
            _LOGGER.info("Removed %s obsolete KEBA entity registry entries", removed)
    except Exception as err:
        # Optional housekeeping must never take monitoring down.
        _LOGGER.error(
            "KEBA registry cleanup failed (%s); monitoring remains active", type(err).__name__
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: P40ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
