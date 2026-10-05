"""Read-only P40 sensors with audited units and reset semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import P40ConfigEntry
from .entity import P40Entity

PARALLEL_UPDATES = 0


def measurement(key, name, device_class, unit, *, category=None):
    return SensorEntityDescription(
        key=key,
        name=name,
        device_class=device_class,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=category,
    )


SENSORS = (
    SensorEntityDescription(key="charging_state", name="Charging state"),
    SensorEntityDescription(key="session_status", name="Session status"),
    measurement("active_power", "Active power", SensorDeviceClass.POWER, UnitOfPower.WATT),
    *(
        measurement(
            f"current_l{i}",
            f"Current L{i}",
            SensorDeviceClass.CURRENT,
            UnitOfElectricCurrent.AMPERE,
        )
        for i in (1, 2, 3)
    ),
    *(
        measurement(
            f"voltage_l{i}",
            f"Voltage L{i}",
            SensorDeviceClass.VOLTAGE,
            UnitOfElectricPotential.VOLT,
        )
        for i in (1, 2, 3)
    ),
    measurement(
        "current_offered",
        "Current offered",
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
    ),
    measurement(
        "maximum_current",
        "Maximum current",
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
    ),
    SensorEntityDescription(
        key="total_energy",
        name="Total energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="session_energy",
        name="Session energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
    ),
    measurement(
        "temperature", "Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS
    ),
    measurement("power_factor", "Power factor", SensorDeviceClass.POWER_FACTOR, PERCENTAGE),
    SensorEntityDescription(
        key="session_start", name="Session start", device_class=SensorDeviceClass.TIMESTAMP
    ),
    SensorEntityDescription(
        key="session_end", name="Session end", device_class=SensorDeviceClass.TIMESTAMP
    ),
    measurement(
        "session_duration", "Session duration", SensorDeviceClass.DURATION, UnitOfTime.SECONDS
    ),
    *(
        SensorEntityDescription(key=key, name=name, entity_category=EntityCategory.DIAGNOSTIC)
        for key, name in (
            ("model", "Model"),
            ("serial", "Serial number"),
            ("package_version", "Package version"),
            ("baseio_firmware", "BaseIO firmware"),
            ("meter_firmware", "Meter firmware"),
            ("safety_firmware", "Safety firmware"),
            ("api_version", "API version"),
            ("rest_alias", "REST alias"),
        )
    ),
    measurement(
        "failsafe_current",
        "Failsafe current",
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
        category=EntityCategory.DIAGNOSTIC,
    ),
    measurement(
        "failsafe_timeout",
        "Failsafe timeout",
        SensorDeviceClass.DURATION,
        UnitOfTime.SECONDS,
        category=EntityCategory.DIAGNOSTIC,
    ),
)


SENSORS = tuple(
    replace(description, name=None, translation_key=description.key) for description in SENSORS
)


async def async_setup_entry(
    hass, entry: P40ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(P40Sensor(entry.runtime_data, description) for description in SENSORS)


class P40Sensor(P40Entity, SensorEntity):
    """Missing/API-failed values are unavailable, not synthetic zero."""

    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.value()

    @property
    def last_reset(self) -> datetime | None:
        if self._key == "session_energy":
            return self.coordinator.data.session.get("session_start")
        return None
