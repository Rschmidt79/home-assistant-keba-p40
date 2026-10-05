"""Offline controls: sockets are disabled globally; no real charger calls."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from aioresponses import aioresponses
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError, CannotConnect, P40Api
from custom_components.keba_p40.controls import (
    DAYS,
    PROFILE_PATH,
    profile_current,
    validate_current,
)
from custom_components.keba_p40.coordinator import P40Coordinator

BASE = "https://p40.local:8443"


def baseline(ma=16000):
    return {
        "name": "CPMP0",
        "socketNumber": 0,
        "stackLevel": 0,
        "profilePurpose": "CHARGE_POINT_MAX_PROFILE",
        "items": [
            {
                "startTime": "00:00:00",
                "stopTime": "24:00:00",
                "daysOfWeek": sorted(DAYS),
                "maxCurrentOffered": ma,
            }
        ],
    }


@pytest.fixture
async def control_client():
    import aiohttp

    async with aiohttp.ClientSession() as session:
        yield P40Api(session, "p40.local", 8443, "fake-user", "fake-password")


@pytest.mark.parametrize("value", [0, 5, 5.999, 16.001, 17, True, None, float("nan"), float("inf")])
def test_out_of_range_locally_rejected(value):
    with pytest.raises(ApiError):
        validate_current(value)


def test_current_and_profile_contract():
    assert validate_current(6) == 6000
    assert validate_current(10) == 10000
    assert validate_current(16) == 16000
    with pytest.raises(ApiError):
        validate_current(16, 10)
    with pytest.raises(ApiError):
        validate_current(10, None)
    assert profile_current(baseline()) == 16
    for key, value in [
        ("active", False),
        ("stackLevel", 1),
        ("socketNumber", 1),
        ("validTo", 123),
        ("relative", True),
    ]:
        p = baseline()
        p[key] = value
        with pytest.raises(ApiError):
            profile_current(p)
    for key, value in [
        ("numberOfPhases", 3),
        ("startTime", "08:00:00"),
        ("maxCurrentOffered", True),
        ("daysOfWeek", ["MONDAY"]),
    ]:
        p = baseline()
        p["items"][0][key] = value
        with pytest.raises(ApiError):
            profile_current(p)


@pytest.mark.parametrize("status", ["REJECTED", "FAILED", "CONFLICT", "NOT_FOUND", "UNKNOWN", None])
async def test_negative_acceptance(control_client, status):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fresh"})
        mock.post(BASE + PROFILE_PATH, payload={"acceptStatus": status})
        with pytest.raises(ApiError):
            await control_client.control(PROFILE_PATH, {"profileItems": baseline()["items"]})


@pytest.mark.parametrize(
    "body", [{}, [], {"msg": "OK"}, {"serialNumber": "wrong", "state": "IDLE"}]
)
async def test_malformed_control_never_accepted(control_client, body):
    path = "/v2/wallboxes/12345678/start-charging"
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fresh"})
        mock.post(BASE + path, payload=body)
        with pytest.raises(ApiError):
            await control_client.control(path)


@pytest.mark.parametrize("body,http", [({"acceptStatus": "ACCEPTED"}, 202), (baseline(10000), 200)])
async def test_documented_profile_success(control_client, body, http):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fresh"})
        mock.post(BASE + PROFILE_PATH, payload=body, status=http)
        assert (
            await control_client.control(PROFILE_PATH, {"profileItems": baseline(10000)["items"]})
            == body
        )


async def test_wallbox_success_timeout_http_no_retry(control_client):
    path = "/v2/wallboxes/12345678/stop-charging"
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fresh"}, repeat=True)
        mock.post(BASE + path, payload={"number": 1, "serialNumber": "12345678", "state": "IDLE"})
        await control_client.control(path)
        mock.post(BASE + path, exception=asyncio.TimeoutError())
        with pytest.raises(CannotConnect):
            await control_client.control(path)
        mock.post(BASE + path, status=500)
        with pytest.raises(ApiError):
            await control_client.control(path)
        mock.post(BASE + path, body="not-json")
        with pytest.raises(ApiError):
            await control_client.control(path)


async def make_coordinator(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data={})
    entry.add_to_hass(hass)
    co = P40Coordinator(hass, entry, mock_api)
    co.async_set_updated_data(await co._async_update_data())
    return co


async def test_current_write_preflight_payload_readback_refresh(hass, mock_api):
    co = await make_coordinator(hass, mock_api)
    get = mock_api.get.side_effect
    written = False

    async def control(path, payload=None):
        nonlocal written
        assert path == PROFILE_PATH
        assert payload["profileItems"][0]["maxCurrentOffered"] == 10000
        assert "numberOfPhases" not in payload["profileItems"][0]
        written = True
        return {"acceptStatus": "ACCEPTED"}

    async def read(path):
        if path == PROFILE_PATH:
            return baseline(10000 if written else 16000)
        return await get(path)

    mock_api.control = AsyncMock(side_effect=control)
    mock_api.get.side_effect = read
    before = mock_api.wallbox.await_count
    await co.async_control("current", 10)
    assert mock_api.wallbox.await_count > before
    assert co.data.configuration["charging_current_limit"] == 10
    # Actual PWM remains the captured physical 16 A; never invent 10 A.
    assert co.data.live["current_offered"] == 16
    assert co.data.configuration["load_management_budget"] == 100
    for invalid in (5, 17):
        with pytest.raises(HomeAssistantError):
            await co.async_control("current", invalid)
    assert mock_api.control.await_count == 1


async def test_failed_readback_and_failed_write_refresh(hass, mock_api):
    co = await make_coordinator(hass, mock_api)
    mock_api.control = AsyncMock(return_value={"acceptStatus": "ACCEPTED"})
    before = mock_api.wallbox.await_count
    with pytest.raises(HomeAssistantError):
        await co.async_control("current", 10)
    assert co.data.configuration["charging_current_limit"] == 16
    assert mock_api.wallbox.await_count > before
    mock_api.control.side_effect = CannotConnect("sanitized")
    before = mock_api.wallbox.await_count
    with pytest.raises(HomeAssistantError):
        await co.async_control("start")
    assert mock_api.wallbox.await_count > before


@pytest.mark.parametrize(
    "action,suffix,payload",
    [
        ("start", "start-charging", None),
        ("stop", "stop-charging", None),
        ("enable", "change-availability", {"available": True}),
        ("disable", "change-availability", {"available": False}),
    ],
)
async def test_action_payload_and_no_optimistic_state(hass, mock_api, action, suffix, payload):
    co = await make_coordinator(hass, mock_api)
    mock_api.control = AsyncMock(return_value={"acceptStatus": "ACCEPTED"})
    await co.async_control(action)
    mock_api.control.assert_awaited_once_with(
        f"/v2/wallboxes/12345678/{suffix}", *([] if payload is None else [payload])
    )
    assert co.data.live["charging"] is False
    assert co.data.live["session_active"] is True


async def test_parallel_expired_requests_one_refresh(control_client):
    control_client._access_token = "expired"
    control_client._refresh_token = "refresh"
    with aioresponses() as mock:
        mock.get(BASE + "/version", status=401)
        mock.post(BASE + "/v2/jwt/refresh", payload={"accessToken": "fresh"})
        mock.get(BASE + "/version", payload="2.5.0", repeat=True)
        assert await asyncio.gather(
            control_client.get("/version"), control_client.get("/version")
        ) == ["2.5.0", "2.5.0"]
        assert (
            sum(len(calls) for (method, _), calls in mock.requests.items() if method == "POST") == 1
        )


async def test_single_box_guard_and_complex_profile(hass, mock_api):
    co = await make_coordinator(hass, mock_api)
    original_get = mock_api.get.side_effect
    mock_api.control = AsyncMock()

    async def get(path):
        if path == "/v2/wallboxes":
            return {"wallboxes": [{"serialNumber": "12345678"}, {"serialNumber": "other"}]}
        return await original_get(path)

    mock_api.get.side_effect = get
    with pytest.raises(HomeAssistantError):
        await co.async_control("current", 10)
    mock_api.control.assert_not_called()


async def test_unavailable_control_and_unsupported_action(hass, mock_api):
    co = await make_coordinator(hass, mock_api)
    with pytest.raises(HomeAssistantError):
        await co.async_control("pause")
    co.async_set_update_error(ApiError("offline"))
    with pytest.raises(HomeAssistantError):
        await co.async_control("start")


async def test_profile_entities_use_physical_data(hass, mock_api):
    from custom_components.keba_p40.button import P40ChargingButton
    from custom_components.keba_p40.number import P40CurrentLimit
    from custom_components.keba_p40.switch import P40Availability

    co = await make_coordinator(hass, mock_api)
    limit, switch, button = P40CurrentLimit(co), P40Availability(co), P40ChargingButton(co, "start")
    assert limit.native_value == 16 and limit.native_max_value == 16
    assert switch.is_on is True
    co.async_control = AsyncMock()
    await limit.async_set_native_value(10)
    await switch.async_turn_off()
    await switch.async_turn_on()
    await button.async_press()
    assert co.async_control.await_count == 4
    assert limit.native_value == 16  # no wish saved
    from dataclasses import replace

    co.async_set_updated_data(
        replace(co.data, live={**co.data.live, "charging_state": "UNAVAILABLE"})
    )
    assert switch.is_on is False
    co.async_set_updated_data(replace(co.data, live={**co.data.live, "charging_state": "OFFLINE"}))
    assert not switch.available


async def test_optional_profile_404_complex_and_transport_failure(hass, mock_api):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    co = await make_coordinator(hass, mock_api)
    original = mock_api.get.side_effect
    mode = "missing"

    async def get(path):
        if path == PROFILE_PATH:
            if mode == "missing":
                raise ApiError("P40 data HTTP 404")
            if mode == "complex":
                return {"items": []}
            raise CannotConnect("transport")
        return await original(path)

    mock_api.get.side_effect = get
    for mode in ("missing", "complex"):
        co._config_due = 0
        data = await co._async_update_data()
        assert data.configuration["charging_current_limit"] is None
        assert data.live["total_energy"] == 123.4567
    mode = "transport"
    co._config_due = 0
    with pytest.raises(UpdateFailed):
        await co._async_update_data()
    with pytest.raises(ApiError):
        profile_current(None)


async def test_feedback_failure_reports_uncertain_control(hass, mock_api):
    co = await make_coordinator(hass, mock_api)
    mock_api.control = AsyncMock(return_value={"acceptStatus": "ACCEPTED"})
    mock_api.wallbox.side_effect = CannotConnect("offline")
    with pytest.raises(HomeAssistantError, match="uncertain"):
        await co.async_control("start")
    assert not co.last_update_success


async def test_control_auth_rejected_and_missing_202(control_client):
    from custom_components.keba_p40.api import InvalidAuth

    path = "/v2/wallboxes/12345678/start-charging"
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fake"}, repeat=True)
        mock.post(BASE + path, status=401)
        with pytest.raises(InvalidAuth):
            await control_client.control(path)
        assert control_client._access_token is None
        mock.post(
            BASE + path,
            status=202,
            payload={"number": 1, "serialNumber": "12345678", "state": "IDLE"},
        )
        with pytest.raises(ApiError, match="Missing"):
            await control_client.control(path)


async def test_actual_entry_reload_keeps_identity_and_never_controls(hass, mock_api):
    from unittest.mock import patch

    from homeassistant.helpers import entity_registry as er

    from .test_setup import DATA

    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        before = {
            e.unique_id: e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        }
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        after = {
            e.unique_id: e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        }
        assert before == after and len(after) == 36
        mock_api.control.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)
