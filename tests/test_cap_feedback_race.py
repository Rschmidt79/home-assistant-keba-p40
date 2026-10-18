"""Deterministic real HA control/poll race; device API fully mocked."""

import asyncio
import copy
import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError


@pytest.mark.parametrize("feedback_fail", [False, True])
async def test_cap_service_waits_for_fresh_profile_despite_inflight_poll(
    hass, mock_api, feedback_fail
):
    original_get = mock_api.get.side_effect
    original_sessions = mock_api.sessions.side_effect
    original_wallbox = mock_api.wallbox.side_effect
    reads = 0

    async def wallbox(serial):
        nonlocal reads
        reads += 1
        if feedback_fail and reads == 3:
            raise ApiError("Synthetic feedback outage")
        return original_wallbox(serial)

    mock_api.wallbox = AsyncMock(side_effect=wallbox)
    cap = 12
    hold = False
    entered = asyncio.Event()
    release = asyncio.Event()
    verified = asyncio.Event()

    async def get(path):
        value = await original_get(path)
        if path == "/v2/profiles/chargepointmaxprofilezero":
            value = copy.deepcopy(value)
            value["items"][0]["maxCurrentOffered"] = cap * 1000
            if cap == 13:
                verified.set()
        return value

    async def sessions(serial):
        nonlocal hold
        if hold:
            hold = False
            entered.set()
            await release.wait()
        return original_sessions(serial)

    async def control(path, body):
        nonlocal cap
        cap = int(body["profileItems"][0]["maxCurrentOffered"] / 1000)
        mock_api.last_request = {"phase": "control", "subtype": "http", "status": 200}
        mock_api.control_result = {"write_attempted": True, "accepted": True}

    mock_api.get = AsyncMock(side_effect=get)
    mock_api.sessions = AsyncMock(side_effect=sessions)
    mock_api.control = AsyncMock(side_effect=control)
    entry = MockConfigEntry(
        domain="keba_p40",
        unique_id="12345678",
        data={
            "host": "example.invalid",
            "port": 8443,
            "username": "synthetic",
            "password": "synthetic",
            "verify_ssl": False,
            "certificate_sha256": "",
        },
    )
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    number = reg.async_get_or_create(
        "number",
        "keba_p40",
        "12345678_charging_current_limit",
        config_entry=entry,
        suggested_object_id="p40_test_cap",
        disabled_by=None,
    )
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        co = entry.runtime_data
        assert float(hass.states.get(number.entity_id).state) == 12
        co._session_due = 0
        co._config_due = co._static_due = time.monotonic() + 3600
        hold = True
        poll = asyncio.create_task(co.async_refresh())
        await asyncio.wait_for(entered.wait(), 2)
        change = asyncio.create_task(
            hass.services.async_call(
                "number", "set_value", {"entity_id": number.entity_id, "value": 13}, blocking=True
            )
        )
        try:
            await asyncio.wait_for(verified.wait(), 2)
            for _ in range(4):
                await asyncio.sleep(0)
            assert not change.done()
            release.set()
            outcomes = await asyncio.wait_for(
                asyncio.gather(poll, change, return_exceptions=True), 3
            )
            await hass.async_block_till_done()
            if feedback_fail:
                assert isinstance(outcomes[1], HomeAssistantError)
                assert hass.states.get(number.entity_id).state == "unavailable"
                assert co.control_receipts["current"]["outcome"] == "feedback_failed"
                assert co._feedback_requested > co._feedback_consumed
                await co.async_refresh()
                await hass.async_block_till_done()
                assert co._feedback_requested == co._feedback_consumed
                assert co.control_receipts["current"]["outcome"] == "feedback_failed"
            else:
                assert outcomes == [None, None]
            observed = float(hass.states.get(number.entity_id).state)
            print(
                {
                    "feedback_outage": feedback_fail,
                    "physical_profile": cap,
                    "ha_number_after_service_or_read_recovery": observed,
                    "receipt": co.control_receipts["current"]["outcome"],
                    "posts": mock_api.control.call_count,
                }
            )
            assert cap == 13
            assert co.control_receipts["current"]["accepted"]
            mock_api.control.assert_awaited_once()
            assert observed == 13
        finally:
            release.set()
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
