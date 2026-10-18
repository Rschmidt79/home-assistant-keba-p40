"""Only curated data, never ConfigEntry.data or API client internals."""

TO_REDACT = {
    "serial",
    "rest_alias",
    "session_id",
    "session_token_id",
    "session_start",
    "session_end",
}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    from dataclasses import asdict

    from homeassistant.components.diagnostics import async_redact_data

    from .const import CONFIG_INTERVAL, LIVE_INTERVAL, SESSION_INTERVAL, STATIC_INTERVAL

    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "profile_observation": dict(
            getattr(coordinator, "profile_observation", {"outcome": "not_observed"})
        ),
        "intervals_seconds": {
            "live": LIVE_INTERVAL,
            "session": SESSION_INTERVAL,
            "configuration": CONFIG_INTERVAL,
            "static": STATIC_INTERVAL,
        },
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }


PHASES = {"preflight", "login", "control", "feedback"}
SUBTYPES = {
    "timeout",
    "connector",
    "tls",
    "disconnected",
    "connection",
    "payload",
    "client",
    "invalid_json",
    "http",
    "schema",
    "unknown",
}


def safe_request(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for key, allowed in [("phase", PHASES), ("subtype", SUBTYPES)]:
        x = value.get(key)
        result[key] = x if isinstance(x, str) and x in allowed else "unknown"
    for key, low, high in [
        ("status", 100, 599),
        ("error_code", -4096, 4096),
        ("elapsed_ms", 0, 86400000),
    ]:
        x = value.get(key)
        result[key] = x if type(x) is int and low <= x <= high else None
    return result


def transport_subtype(error, aiohttp):
    # Class checks only: never stringify/repr exceptions or their attributes.
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch)):
        return "tls"
    if isinstance(error, aiohttp.ClientConnectorError):
        return "connector"
    if isinstance(error, aiohttp.ServerDisconnectedError):
        return "disconnected"
    if isinstance(error, aiohttp.ClientPayloadError):
        return "payload"
    if isinstance(error, aiohttp.ClientConnectionError):
        return "connection"
    return "client"


def safe_profile_shape(body):
    """Parser predicates only: no raw keys, values, names, timestamps or auth.

    Observe the existing authenticated poll; do not request or retain raw data.
    Counts are bounded categories to avoid reflecting arbitrary integer payloads.
    """
    import time

    from .controls import DAYS

    result = {"mapping": isinstance(body, dict)}
    if not result["mapping"]:
        return result
    valid_from = body.get("validFrom")
    items = body.get("items")
    result.update(
        name_nonempty=isinstance(body.get("name"), str) and bool(body["name"]),
        purpose_supported=body.get("profilePurpose") == "CHARGE_POINT_MAX_PROFILE",
        socket_zero=type(body.get("socketNumber")) is int and body["socketNumber"] == 0,
        stack_zero=type(body.get("stackLevel", 0)) is int and body.get("stackLevel", 0) == 0,
        active=body.get("active", True) is True,
        absolute=body.get("relative", False) is False,
        valid_from_absent_or_null=valid_from is None,
        valid_from_past_or_now=type(valid_from) is int and 0 <= valid_from <= time.time() * 1000,
        expiry_absent_or_null=body.get("validTo") is None,
        validity_unbounded=body.get("validFrom") is None and body.get("validTo") is None,
        items_list=isinstance(items, list),
        item_count=("zero" if not items else "one" if len(items) == 1 else "multiple")
        if isinstance(items, list)
        else "not_list",
    )
    if not isinstance(items, list) or len(items) != 1:
        return result
    item = items[0]
    result["item_mapping"] = isinstance(item, dict)
    if not isinstance(item, dict):
        return result
    days, current = item.get("daysOfWeek"), item.get("maxCurrentOffered")
    current_integer = type(current) is int and current >= 0
    result.update(
        starts_at_midnight=item.get("startTime") == "00:00:00",
        ends_at_day_end=item.get("stopTime") == "24:00:00",
        all_week=isinstance(days, list)
        and all(isinstance(x, str) for x in days)
        and set(days) == DAYS,
        phase_setting_absent="numberOfPhases" not in item,
        phase_setting_null="numberOfPhases" in item and item.get("numberOfPhases") is None,
        phase_setting_explicit=item.get("numberOfPhases") is not None,
        current_nonnegative_integer=current_integer,
        current_in_entity_range=current_integer and 6000 <= current <= 16000,
    )
    return result
