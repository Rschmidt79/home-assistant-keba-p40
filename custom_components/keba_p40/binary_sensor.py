"""P40 status flags; session-open and charging are independent."""

from dataclasses import replace

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import P40ConfigEntry
from .entity import P40Entity

PARALLEL_UPDATES = 0
BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="vehicle_plugged", name="Vehicle plugged", device_class=BinarySensorDeviceClass.PLUG
    ),
    BinarySensorEntityDescription(
        key="charging", name="Charging", device_class=BinarySensorDeviceClass.BATTERY_CHARGING
    ),
    BinarySensorEntityDescription(key="session_active", name="Session active"),
    BinarySensorEntityDescription(
        key="error", name="Error", device_class=BinarySensorDeviceClass.PROBLEM
    ),
)


BINARY_SENSORS = tuple(
    replace(description, name=None, translation_key=description.key)
    for description in BINARY_SENSORS
)


async def async_setup_entry(
    hass, entry: P40ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        P40BinarySensor(entry.runtime_data, description) for description in BINARY_SENSORS
    )


class P40BinarySensor(P40Entity, BinarySensorEntity):
    def __init__(self, coordinator, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.value()
