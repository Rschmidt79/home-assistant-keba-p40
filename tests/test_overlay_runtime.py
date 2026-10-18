"""Regression coverage for the exact production overlay retained in this release."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError, CannotConnect
from custom_components.keba_p40.entity import P40Entity
from custom_components.keba_p40.sensor import SENSORS, P40Sensor

from .test_coordinator import coordinator
from .test_setup import DATA


def test_no_number_value_property_collision():
    assert "value" not in vars(P40Entity)


async def test_real_meter_entity_publishes_equal_meter_observation_and_invalidates(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        co = entry.runtime_data
        registry = er.async_get(hass)
        eid = registry.async_get_entity_id("sensor", "keba_p40", "12345678_total_energy")
        before = hass.states.get(eid)
        token = before.attributes["continuity_token"]
        stamp = before.attributes["observation_end"]
        with patch(
            "custom_components.keba_p40.coordinator.time.time", return_value=time.time() + 1
        ):
            await co.async_refresh()
            await hass.async_block_till_done()
        after = hass.states.get(eid)
        assert after.state == before.state == "123.4567"
        assert after.attributes["continuity_token"] == token
        assert after.attributes["observation_end"] > stamp
        assert after.attributes["observed_meter_kwh"] == float(after.state)
        mock_api.wallbox.side_effect = ApiError("synthetic outage")
        await co.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(eid).state == "unavailable"
        assert not co.meter_observations
        assert co.meter_continuity_token != token
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not co._meter_listeners


async def test_start_receipt_survives_current_write(hass, mock_api):
    co = coordinator(hass, mock_api)
    await co.async_refresh()

    async def accepted(*args, **kwargs):
        mock_api.last_request = {"phase": "control", "subtype": "http", "status": 200}
        mock_api.control_result = {"write_attempted": True, "accepted": True}

    mock_api.control = AsyncMock(side_effect=accepted)
    await co.async_control("start")
    start = dict(co.control_receipts["start"])
    assert start["accepted"] and start["feedback_available"]
    await co.async_control("current", 16)
    assert co.last_control["action"] == "current"
    assert co.control_receipts["start"] == start
    assert co.last_control["attempt_id"] != start["attempt_id"]
    sensor = P40Sensor(co, next(d for d in SENSORS if d.key == "control_result"))
    assert sensor.extra_state_attributes["start_receipt"] == start
    assert sensor.native_value == "accepted"


async def test_uncertain_stop_is_recorded_once_with_feedback_and_no_replay(hass, mock_api):
    co = coordinator(hass, mock_api)
    await co.async_refresh()

    async def uncertain(*args, **kwargs):
        mock_api.last_request = {"phase": "control", "subtype": "timeout", "status": None}
        mock_api.control_result = {"write_attempted": True, "accepted": False}
        raise CannotConnect("synthetic timeout")

    mock_api.control = AsyncMock(side_effect=uncertain)
    prior_reads = mock_api.wallbox.call_count
    with pytest.raises(HomeAssistantError):
        await co.async_control("stop")
    mock_api.control.assert_awaited_once()
    assert mock_api.wallbox.call_count > prior_reads
    receipt = co.control_receipts["stop"]
    assert receipt["outcome"] == "uncertain"
    assert receipt["write_attempted"] and not receipt["accepted"]
    assert receipt["feedback_available"]
