"""Upgrade/reload contract for existing public and patched 0.2.4 installations."""

from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.binary_sensor import BINARY_SENSORS
from custom_components.keba_p40.sensor import SENSORS

from .test_setup import DATA


@pytest.mark.parametrize("patched", [False, True], ids=["public-0.2.4", "patched-0.2.4"])
async def test_existing_install_retains_identity_settings_and_controls(hass, mock_api, patched):
    entry = MockConfigEntry(
        domain="keba_p40",
        unique_id="12345678",
        version=2,
        data=DATA,
        options={"retained_user_option": "unchanged"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("keba_p40", "12345678")},
    )
    dr.async_get(hass).async_update_device(device.id, name_by_user="Existing driveway charger")
    records = []
    for domain, descriptions in (("sensor", SENSORS), ("binary_sensor", BINARY_SENSORS)):
        for description in descriptions:
            if description.key == "control_result" and not patched:
                continue
            records.append(
                registry.async_get_or_create(
                    domain,
                    "keba_p40",
                    f"12345678_{description.key}",
                    config_entry=entry,
                    device_id=device.id,
                    suggested_object_id=f"existing_driveway_{description.key}",
                    disabled_by=er.RegistryEntryDisabler.USER
                    if description.key == "temperature"
                    else None,
                )
            )
    for domain, key in (
        ("number", "charging_current_limit"),
        ("button", "start_charging"),
        ("button", "stop_charging"),
        ("switch", "charging_availability"),
    ):
        records.append(
            registry.async_get_or_create(
                domain,
                "keba_p40",
                f"12345678_{key}",
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=f"existing_driveway_{key}",
                disabled_by=er.RegistryEntryDisabler.USER
                if key == "charging_availability"
                else None,
            )
        )
    before = {r.unique_id: (r.entity_id, r.disabled_by, r.device_id) for r in records}
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        for cycle in range(2):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert dict(entry.data) == DATA
            assert dict(entry.options) == {"retained_user_option": "unchanged"}
            assert entry.unique_id == "12345678" and entry.version == 2
            current = er.async_entries_for_config_entry(registry, entry.entry_id)
            assert len(current) == 38
            for r in current:
                if r.unique_id in before:
                    assert (r.entity_id, r.disabled_by, r.device_id) == before[r.unique_id]
            assert (
                dr.async_get(hass).async_get(device.id).name_by_user == "Existing driveway charger"
            )
            cap_id = before["12345678_charging_current_limit"][0]
            assert float(hass.states.get(cap_id).state) == 16
            mock_api.control.assert_not_called()
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
