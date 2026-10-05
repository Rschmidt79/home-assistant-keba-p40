"""Charging current cap; not the load-management budget."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.helpers.entity import EntityCategory

from .entity import P40Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([P40CurrentLimit(entry.runtime_data)])


class P40CurrentLimit(P40Entity, NumberEntity):
    _attr_translation_key = "charging_current_limit"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 6
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "charging_current_limit")

    @property
    def available(self):
        maximum = self.coordinator.data.live.get("maximum_current")
        return super().available and maximum is not None and maximum >= 6

    @property
    def native_max_value(self):
        maximum = self.coordinator.data.live.get("maximum_current")
        return min(16, maximum) if maximum is not None else 16

    @property
    def native_value(self):
        return self.value()

    async def async_set_native_value(self, value):
        await self.coordinator.async_control("current", value)
