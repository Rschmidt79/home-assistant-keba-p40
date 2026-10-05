"""Only curated data, never ConfigEntry.data or API client internals."""

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import P40ConfigEntry
from .const import CONFIG_INTERVAL, LIVE_INTERVAL, SESSION_INTERVAL, STATIC_INTERVAL

TO_REDACT = {"serial", "rest_alias", "session_id", "session_start", "session_end"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: P40ConfigEntry) -> dict:
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "intervals_seconds": {
            "live": LIVE_INTERVAL,
            "session": SESSION_INTERVAL,
            "configuration": CONFIG_INTERVAL,
            "static": STATIC_INTERVAL,
        },
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
