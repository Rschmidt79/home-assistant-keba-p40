"""Parse only KEBA fields and units confirmed by the authenticated audit."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .api import ApiError
from .const import ERROR_STATES, SESSION_STATES, STATES


def number(value: Any, divisor: float = 1, *, signed: bool = False) -> float | None:
    """Missing/invalid measurements stay unknown, never zero fallbacks."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or (value < 0 and not signed):
        return None
    return value / divisor


def text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def timestamp_ms(value: Any) -> datetime | None:
    seconds = number(value, 1000)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except OverflowError, OSError, ValueError:
        return None


def config_pairs(body: Any) -> dict[str, str]:
    """KEBA returns configuration values as strings, including booleans."""
    if not isinstance(body, dict) or not isinstance(body.get("configs"), list):
        raise ApiError("Invalid configuration response")
    return {
        pair["key"]: pair["value"]
        for pair in body["configs"]
        if isinstance(pair, dict)
        and isinstance(pair.get("key"), str)
        and isinstance(pair.get("value"), str)
    }


def config_number(values: dict[str, str], key: str, divisor: float = 1) -> float | None:
    try:
        raw = float(values[key])
    except KeyError, ValueError:
        return None
    return number(raw, divisor)


@dataclass(frozen=True)
class P40Data:
    """Allowlisted normalized data; never credentials, JWT or raw auth state."""

    live: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)


def parse_wallbox(body: dict[str, Any]) -> dict[str, Any]:
    meter = body.get("meter") if isinstance(body.get("meter"), dict) else {}
    raw_state = body.get("state")
    state = raw_state if isinstance(raw_state, str) and raw_state in STATES else None
    result: dict[str, Any] = {
        "vehicle_plugged": boolean(body.get("vehiclePlugged")),
        "session_active": boolean(body.get("sessionActive")),
        "charging_state": state,
        # SessionActive/currentOffered/power alone cannot mean CHARGING.
        "charging": state == "CHARGING" if state else None,
        "error": state in ERROR_STATES if state else None,
        "active_power": number(meter.get("totalActivePower"), 1000),
        "current_offered": number(meter.get("currentOffered"), 1000),
        "maximum_current": number(body.get("maxCurrent"), 1000),
        "total_energy": number(meter.get("meterValue"), 1_000_000),
        "temperature": number(meter.get("temperature"), 100, signed=True),
        "power_factor": number(meter.get("totalPowerFactor"), 10),
        "model": text(body.get("model")),
        "baseio_firmware": text(body.get("firmwareVersion")),
        "meter_firmware": text(body.get("firmwareVersionMetering")),
        "safety_firmware": text(body.get("firmwareVersionSafety")),
        "authorization_enabled": boolean(body.get("authorizationEnabled")),
    }
    lines = meter.get("lines")
    if not isinstance(lines, list):
        lines = []
    for phase in ("L1", "L2", "L3"):
        line = next(
            (line for line in lines if isinstance(line, dict) and line.get("socketPhase") == phase),
            {},
        )
        result[f"current_{phase.lower()}"] = number(line.get("current"), 1000)
        result[f"voltage_{phase.lower()}"] = number(line.get("voltage"))
    return result


def parse_sessions(body: Any, serial: str) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("sessions"), list):
        raise ApiError("Invalid sessions response")
    records = [
        s
        for s in body["sessions"]
        if isinstance(s, dict)
        and s.get("wallboxSerialNumber") == serial
        and isinstance(s.get("status"), str)
        and s["status"] in SESSION_STATES
        and isinstance(s.get("id"), int)
        and not isinstance(s["id"], bool)
    ]
    if not records:
        return {}
    records.sort(key=lambda s: number(s.get("startDate")) or -1, reverse=True)
    # Prefer the open session; after closing expose the latest completed session.
    selected = next(
        (s for s in records if s["status"] != "CLOSED" and s.get("endDate") is None), records[0]
    )
    start = timestamp_ms(selected.get("startDate"))
    return {
        "session_id": selected["id"],
        "session_status": selected["status"],
        "session_start": start,
        "session_end": timestamp_ms(selected.get("endDate")),
        "session_duration": number(selected.get("duration"), 1000),
        # Audit confirmed rounded energyConsumedInKwh differs from exact energyConsumed.
        # A known reset timestamp is required for correct TOTAL statistics.
        "session_energy": number(selected.get("energyConsumed"), 1_000_000) if start else None,
    }
