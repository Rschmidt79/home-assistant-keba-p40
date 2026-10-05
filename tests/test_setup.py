from unittest.mock import patch

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError

DATA = {
    "host": "p40.local",
    "port": 8443,
    "username": "example-user",
    "password": "example-password",
    "verify_ssl": False,
    "certificate_sha256": "",
}


async def test_actual_ha_setup_entities_failure_recovery_unload(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert len(entities) == 36
        assert len([entity for entity in entities if entity.disabled_by is None]) == 32
        assert {entity.domain for entity in entities} == {
            "sensor",
            "binary_sensor",
            "number",
            "button",
            "switch",
        }
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert len(devices) == 1
        assert devices[0].identifiers == {("keba_p40", "12345678")}
        indexed = {entity.unique_id: entity.entity_id for entity in entities}
        assert hass.states.get(indexed["12345678_total_energy"]).state == "123.4567"
        assert hass.states.get(indexed["12345678_session_energy"]).state == "15.1234"
        assert (
            hass.states.get(indexed["12345678_session_energy"]).attributes["state_class"] == "total"
        )
        assert (
            hass.states.get(indexed["12345678_session_energy"]).attributes["last_reset"]
            == "2026-01-05T09:12:13.728000+00:00"
        )
        assert hass.states.get(indexed["12345678_charging"]).state == "off"
        assert hass.states.get(indexed["12345678_session_active"]).state == "on"
        assert hass.states.get(indexed["12345678_session_end"]).state == STATE_UNAVAILABLE
        mock_api.wallbox.side_effect = ApiError("private value")
        await entry.runtime_data.async_refresh()
        assert all(
            hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
            for entity in entities
            if entity.disabled_by is None
        )
        from .conftest import load

        mock_api.wallbox.side_effect = lambda serial: load("wallbox")
        await entry.runtime_data.async_refresh()
        assert hass.states.get(indexed["12345678_total_energy"]).state == "123.4567"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        mock_api.close.assert_called()


async def test_setup_failure_does_not_keep_auth_in_memory(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    mock_api.identity.side_effect = ApiError("unavailable")
    with patch("custom_components.keba_p40.make_api", return_value=mock_api):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        mock_api.close.assert_called_once()


async def test_legacy_entry_migrates_implicit_admin_and_options(hass, mock_api):
    old = {key: value for key, value in DATA.items() if key != "username"}
    entry = MockConfigEntry(
        domain="keba_p40",
        title="KEBA P40 12345678",
        unique_id="12345678",
        version=1,
        data=old,
        options={"host": "192.0.2.14", "password": "updated-fake-password"},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.keba_p40.make_api", return_value=mock_api) as factory:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.version == 2
        assert entry.data["username"] == "admin"
        assert entry.data["host"] == "192.0.2.14"
        assert entry.data["password"] == "updated-fake-password"
        assert dict(entry.options) == {}
        assert entry.unique_id == "12345678"
        factory.assert_called_once_with(hass, entry.data)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_idempotent_and_future_version_rejected(hass):
    from custom_components.keba_p40 import async_migrate_entry

    entry = MockConfigEntry(domain="keba_p40", version=2, unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.data["username"] == "example-user"
    hass.config_entries.async_update_entry(entry, version=3)
    assert not await async_migrate_entry(hass, entry)


async def test_legacy_api_admin_default_and_missing_password(hass):
    import pytest
    from homeassistant.exceptions import ConfigEntryAuthFailed

    from custom_components.keba_p40 import make_api

    data = {key: value for key, value in DATA.items() if key != "username"}
    api = make_api(hass, data)
    assert api._username == "admin"
    api.close()
    data.pop("password")
    with pytest.raises(ConfigEntryAuthFailed):
        make_api(hass, data)
