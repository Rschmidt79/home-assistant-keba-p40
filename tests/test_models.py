import math
from datetime import UTC, datetime

import pytest

from custom_components.keba_p40.api import ApiError
from custom_components.keba_p40.models import (
    boolean,
    config_number,
    config_pairs,
    number,
    parse_sessions,
    parse_wallbox,
    timestamp_ms,
)


def test_real_response_scaling_and_semantics(payloads):
    w = parse_wallbox(payloads["wallbox"])
    assert w["vehicle_plugged"] is True
    assert w["session_active"] is True
    assert w["charging"] is False
    assert w["charging_state"] == "READY_FOR_CHARGING"
    assert w["active_power"] == 0
    assert w["current_offered"] == 16
    assert [w[f"current_l{i}"] for i in (1, 2, 3)] == [0.005, 0.004, 0.005]
    assert [w[f"voltage_l{i}"] for i in (1, 2, 3)] == [231, 233, 234]
    assert w["total_energy"] == 123.4567
    assert w["temperature"] == 31.10
    assert w["power_factor"] == 0
    assert w["baseio_firmware"] == "5.0.1"
    assert w["authorization_enabled"] is False
    assert w["error"] is False


def test_precise_session_energy_timestamps_duration(payloads):
    session = parse_sessions(payloads["sessions"], "12345678")
    assert session["session_energy"] == 15.1234
    assert session["session_energy"] != payloads["sessions"]["sessions"][0]["energyConsumedInKwh"]
    assert session["session_start"] == datetime(2026, 1, 5, 9, 12, 13, 728000, UTC)
    assert session["session_end"] is None
    assert session["session_duration"] == 7200.0
    assert session["session_status"] == "BLOCKED"


def test_closed_session_and_other_device_filtered(payloads):
    payloads["sessions"]["sessions"][0]["wallboxSerialNumber"] = "another-device"
    s = parse_sessions(payloads["sessions"], "12345678")
    assert s["session_status"] == "CLOSED"
    assert (s["session_end"] - s["session_start"]).total_seconds() == s["session_duration"]
    assert parse_sessions({"sessions": []}, "12345678") == {}


def test_missing_fields_do_not_become_zero():
    w = parse_wallbox({})
    assert w["active_power"] is None
    assert w["charging"] is None
    assert w["current_l1"] is None
    assert boolean("false") is None
    assert number(True) is None
    assert number(float("nan")) is None
    assert number(math.inf) is None
    assert timestamp_ms("1767604333728") is None
    assert timestamp_ms(10**30) is None
    assert config_number({}, "unknown") is None
    assert config_number({"x": "invalid"}, "x") is None
    with pytest.raises(ApiError):
        config_pairs({"configs": "wrong"})
    with pytest.raises(ApiError):
        parse_sessions({}, "12345678")


def test_energy_requires_real_session_reset_timestamp():
    s = parse_sessions(
        {
            "sessions": [
                {
                    "id": 1,
                    "wallboxSerialNumber": "12345678",
                    "status": "BLOCKED",
                    "energyConsumed": 100,
                }
            ]
        },
        "12345678",
    )
    assert s["session_energy"] is None


@pytest.mark.parametrize(
    "state,charging,error",
    [
        ("CHARGING", True, False),
        ("SUSPENDED", False, False),
        ("DEGRADED", False, True),
        ("UNRECOVERABLE_ERROR", False, True),
        ("UNAVAILABLE", False, False),
        ("not-documented", None, None),
    ],
)
def test_charging_uses_state_not_session_or_pwm(state, charging, error):
    w = parse_wallbox(
        {
            "state": state,
            "sessionActive": True,
            "meter": {"currentOffered": 16000, "totalActivePower": 0},
        }
    )
    assert w["charging"] is charging
    assert w["error"] is error


def test_malformed_enum_and_negative_celsius_are_handled():
    assert parse_wallbox({"state": {"invalid": True}})["charging"] is None
    assert parse_wallbox({"meter": {"temperature": -500}})["temperature"] == -5
    assert (
        parse_sessions(
            {"sessions": [{"status": [], "wallboxSerialNumber": "12345678"}]}, "12345678"
        )
        == {}
    )
