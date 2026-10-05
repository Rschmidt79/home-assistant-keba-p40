import json
from dataclasses import replace
from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.binary_sensor import BINARY_SENSORS, P40BinarySensor
from custom_components.keba_p40.coordinator import P40Coordinator
from custom_components.keba_p40.diagnostics import async_get_config_entry_diagnostics
from custom_components.keba_p40.sensor import SENSORS, P40Sensor


async def test_entities_reset_identity_availability_and_diagnostics(hass, mock_api):
    entry = MockConfigEntry(
        domain="keba_p40",
        unique_id="12345678",
        data={"username": "example-user", "password": "example-password"},
    )
    entry.add_to_hass(hass)
    co = P40Coordinator(hass, entry, mock_api)
    co.async_set_updated_data(await co._async_update_data())
    entry.runtime_data = co
    sensors = {d.key: P40Sensor(co, d) for d in SENSORS}
    binaries = {d.key: P40BinarySensor(co, d) for d in BINARY_SENSORS}
    assert len(sensors) == 28
    assert len(binaries) == 4
    assert sensors["total_energy"].native_value == 123.4567
    assert sensors["total_energy"].state_class == SensorStateClass.TOTAL_INCREASING
    session = sensors["session_energy"]
    assert session.native_value == 15.1234
    assert session.state_class == SensorStateClass.TOTAL
    assert session.last_reset == datetime(2026, 1, 5, 9, 12, 13, 728000, UTC)
    co.async_set_updated_data(
        replace(
            co.data,
            session={
                **co.data.session,
                "session_id": 1002,
                "session_start": datetime(2026, 1, 6, tzinfo=UTC),
                "session_energy": 0.001,
            },
        )
    )
    assert session.last_reset == datetime(2026, 1, 6, tzinfo=UTC)
    assert session.native_value == 0.001
    assert binaries["session_active"].is_on is True
    assert binaries["charging"].is_on is False
    assert binaries["error"].device_class.value == "problem"
    assert sensors["temperature"].device_class == SensorDeviceClass.TEMPERATURE
    assert sensors["serial"].unique_id == "12345678_serial"
    assert sensors["serial"].device_info["identifiers"] == {("keba_p40", "12345678")}
    assert sensors["serial"].device_info["name"] == "P40_12345678"
    assert not sensors["session_end"].available
    co.async_set_update_error(RuntimeError("test"))
    assert not any(ent.available for ent in [*sensors.values(), *binaries.values()])
    diag = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diag, default=str)
    assert "example-user" not in serialized and "example-password" not in serialized
    assert "12345678" not in serialized and "P40_12345678" not in serialized
    assert "_access_token" not in serialized and "Authorization" not in serialized
