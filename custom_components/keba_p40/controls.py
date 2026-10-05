"""Documented control contracts. No automatic control or phase switching."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api import ApiError

PROFILE_PATH = "/v2/profiles/chargepointmaxprofilezero"
DAYS = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}


def validate_current(value: Any, maximum: float | None = 16) -> int:
    """Fail closed: 0 is not a pause API; range is 6..min(16, hardware)."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or maximum is None
        or not 6 <= value <= min(16, maximum)
        or round(value * 1000) != value * 1000
    ):
        raise ApiError("Charging current must be between 6 and the verified maximum (up to 16 A)")
    return round(value * 1000)


def profile_current(body: Any) -> float:
    """Only a simple, active, all-day level-zero CP maximum profile is editable.

    Never overwrite schedules, Tx profiles, validity windows or phase settings.
    This is a documented but not physically audited response schema.
    """
    if not isinstance(body, dict):
        raise ApiError("Invalid charging profile response")
    items = body.get("items")
    if (
        not isinstance(body.get("name"), str)
        or not body["name"]
        or body.get("profilePurpose") != "CHARGE_POINT_MAX_PROFILE"
        or type(body.get("socketNumber")) is not int
        or body.get("socketNumber") != 0
        or type(body.get("stackLevel", 0)) is not int
        or body.get("stackLevel", 0) != 0
        or body.get("active", True) is not True
        or body.get("relative", False) is not False
        or body.get("validFrom") is not None
        or body.get("validTo") is not None
        or not isinstance(items, list)
        or len(items) != 1
    ):
        raise ApiError("Charging profile is not a simple editable baseline")
    item = items[0]
    if (
        not isinstance(item, dict)
        or item.get("startTime") != "00:00:00"
        or item.get("stopTime") != "24:00:00"
        or not isinstance(item.get("daysOfWeek"), list)
        or not all(isinstance(day, str) for day in item["daysOfWeek"])
        or set(item["daysOfWeek"]) != DAYS
        or "numberOfPhases" in item
    ):
        raise ApiError("Scheduled or phase-specific profile cannot be changed")
    value = item.get("maxCurrentOffered")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError("Invalid profile current")
    return value / 1000


async def execute_control(coordinator, action: str, current: float | None) -> None:
    """Accepted command is followed by physical reads; never cache a wish."""
    api, serial = coordinator.api, coordinator.serial
    try:
        if not coordinator.last_update_success:
            raise ApiError("P40 state is unavailable")
        if action == "current":
            maximum = coordinator.data.live.get("maximum_current")
            ma = validate_current(current, maximum)
            # Baseline is charge-point-wide: require exactly this one wallbox.
            boxes = await api.get("/v2/wallboxes")
            if (
                not isinstance(boxes, dict)
                or not isinstance(boxes.get("wallboxes"), list)
                or len(boxes["wallboxes"]) != 1
                or boxes["wallboxes"][0].get("serialNumber") != serial
            ):
                raise ApiError("Current control requires a single-wallbox installation")
            existing = await api.get(PROFILE_PATH)
            profile_current(existing)
            item = dict(existing["items"][0])
            item["maxCurrentOffered"] = ma
            await api.control(PROFILE_PATH, {"profileItems": [item]})
            confirmed = profile_current(await api.get(PROFILE_PATH))
            if confirmed != ma / 1000:
                raise ApiError("Physical profile does not confirm requested limit")
            coordinator._config_due = 0
        elif action in ("start", "stop"):
            await api.control(f"/v2/wallboxes/{serial}/{action}-charging")
        elif action in ("enable", "disable"):
            await api.control(
                f"/v2/wallboxes/{serial}/change-availability",
                {"available": action == "enable"},
            )
        else:
            raise ApiError("Unsupported control")
    except ApiError:
        # Never expose response bodies, password, token or URLs in HA errors.
        raise HomeAssistantError("KEBA control failed; inspect refreshed physical state") from None
