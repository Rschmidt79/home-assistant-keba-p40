from unittest.mock import patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError, InvalidAuth
from custom_components.keba_p40.coordinator import P40Coordinator


def coordinator(hass, api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data={})
    entry.add_to_hass(hass)
    return P40Coordinator(hass, entry, api)


async def test_staggered_polling_no_extra_requests(hass, mock_api):
    co = coordinator(hass, mock_api)
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=100):
        co.async_set_updated_data(await co._async_update_data())
    assert mock_api.wallbox.call_count == 1
    assert mock_api.sessions.call_count == 1
    assert mock_api.get.call_count == 8
    for when in [105, 110, 115]:
        with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=when):
            co.async_set_updated_data(await co._async_update_data())
    assert mock_api.wallbox.call_count == 4
    assert mock_api.sessions.call_count == 1
    assert mock_api.get.call_count == 8
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=120):
        co.async_set_updated_data(await co._async_update_data())
    assert mock_api.sessions.call_count == 2
    assert mock_api.get.call_count == 8
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=220):
        co.async_set_updated_data(await co._async_update_data())
    assert mock_api.get.call_count == 11
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=21700):
        co.async_set_updated_data(await co._async_update_data())
    assert mock_api.get.call_count == 19


async def test_failed_group_deadlines_not_committed_and_auth_flow(hass, mock_api):
    co = coordinator(hass, mock_api)
    mock_api.sessions.side_effect = ApiError("private payload is never logged")
    with pytest.raises(UpdateFailed, match="REST data unavailable"):
        await co._async_update_data()
    assert co._session_due == 0 and co._config_due == 0
    mock_api.wallbox.side_effect = InvalidAuth("secret")
    with pytest.raises(ConfigEntryAuthFailed) as err:
        await co._async_update_data()
    assert "secret" not in str(err.value)


async def test_identity_and_transition(hass, mock_api, payloads):
    co = coordinator(hass, mock_api)
    await co._async_setup()
    mock_api.identity.return_value = "wrong"
    with pytest.raises(UpdateFailed):
        await co._async_setup()
    mock_api.identity.side_effect = InvalidAuth("not logged")
    with pytest.raises(ConfigEntryAuthFailed):
        await co._async_setup()
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=100):
        co.async_set_updated_data(await co._async_update_data())
    wallbox = payloads["wallbox"]
    wallbox["vehiclePlugged"] = False
    mock_api.wallbox.side_effect = None
    mock_api.wallbox.return_value = wallbox
    with patch("custom_components.keba_p40.coordinator.time.monotonic", return_value=105):
        await co._async_update_data()
    assert mock_api.sessions.call_count == 2


async def test_failure_marks_coordinator_unavailable_and_recovery(hass, mock_api):
    co = coordinator(hass, mock_api)
    await co.async_refresh()
    assert co.last_update_success
    mock_api.wallbox.side_effect = ApiError("failed")
    await co.async_refresh()
    assert not co.last_update_success
    assert co.data.live["total_energy"] == 123.4567
    from .conftest import load

    mock_api.wallbox.side_effect = lambda serial: load("wallbox")
    await co.async_refresh()
    assert co.last_update_success
