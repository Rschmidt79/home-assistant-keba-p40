"""Proven old identifiers only: real HA registry, no wallbox/network calls."""

from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40 import LEGACY_ENTITY_KEYS, _async_remove_legacy_entities
from custom_components.keba_p40.binary_sensor import BINARY_SENSORS
from custom_components.keba_p40.sensor import SENSORS

from .test_setup import DATA

SERIAL = "12345678"


def create_current(registry, entry):
    return [
        registry.async_get_or_create(domain, "keba_p40", f"{SERIAL}_{d.key}", config_entry=entry)
        for domain, descriptions in (("sensor", SENSORS), ("binary_sensor", BINARY_SENSORS))
        for d in descriptions
    ]


def create_legacy(registry, entry):
    return [
        registry.async_get_or_create(
            domain, "keba_p40", f"keba_p40_{SERIAL}_{key}", config_entry=entry
        )
        for domain, keys in LEGACY_ENTITY_KEYS.items()
        for key in keys
    ]


async def test_cleanup_exact_25_and_preserves_other_records(hass):
    entry = MockConfigEntry(domain="keba_p40", unique_id=SERIAL, data=DATA)
    other = MockConfigEntry(domain="keba_p40", unique_id="99999999", data=DATA)
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    new = create_current(registry, entry)
    old = create_legacy(registry, entry)
    assert len(new) == 32 and len(old) == 25
    controls = [
        registry.async_get_or_create(domain, "keba_p40", f"{SERIAL}_{key}", config_entry=entry)
        for domain, key in [
            ("number", "charging_current_limit"),
            ("button", "start_charging"),
            ("button", "stop_charging"),
            ("switch", "charging_availability"),
        ]
    ]
    preserved = [
        registry.async_get_or_create(
            "sensor", "keba_p40", f"keba_p40_{SERIAL}_unknown", config_entry=entry
        ),
        registry.async_get_or_create(
            "sensor", "keba_p40", "keba_p40_99999999_state", config_entry=other
        ),
        registry.async_get_or_create(
            "sensor", "other_platform", f"keba_p40_{SERIAL}_state", config_entry=entry
        ),
        registry.async_get_or_create(
            "switch", "keba_p40", f"keba_p40_{SERIAL}_state", config_entry=entry
        ),
    ]
    assert _async_remove_legacy_entities(hass, entry) == 25
    assert all(registry.async_get(e.entity_id) is None for e in old)
    assert all(registry.async_get(e.entity_id) is not None for e in [*new, *controls, *preserved])
    assert _async_remove_legacy_entities(hass, entry) == 0


async def test_no_cleanup_until_all_current_entities_registered(hass):
    entry = MockConfigEntry(domain="keba_p40", unique_id=SERIAL, data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = create_legacy(registry, entry)
    assert _async_remove_legacy_entities(hass, entry) == 0
    assert len(old) == 25
    assert all(registry.async_get(e.entity_id) for e in old)


@pytest.mark.parametrize("serial", [None, "alias", ""])
async def test_invalid_identity_never_cleans(hass, serial):
    entry = MockConfigEntry(domain="keba_p40", unique_id=serial, data=DATA)
    entry.add_to_hass(hass)
    assert _async_remove_legacy_entities(hass, entry) == 0


async def test_actual_setup_cleans_legacy_and_keeps_36(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id=SERIAL, data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = create_legacy(registry, entry)
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert all(registry.async_get(e.entity_id) is None for e in old)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert len(entries) == 36
        assert len([e for e in entries if e.disabled_by is None]) == 32
        mock_api.control.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_cleanup_failure_never_breaks_monitoring(hass, mock_api, caplog):
    entry = MockConfigEntry(domain="keba_p40", unique_id=SERIAL, data=DATA)
    entry.add_to_hass(hass)
    with (
        patch("custom_components.keba_p40.make_api", return_value=mock_api),
        patch(
            "custom_components.keba_p40._async_remove_legacy_entities",
            side_effect=RuntimeError("private text"),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.last_update_success
        assert "monitoring remains active" in caplog.text
        assert "private text" not in caplog.text
        assert await hass.config_entries.async_unload(entry.entry_id)
