"""Availability is operational in/out-of-order status, not session pause."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import P40Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([P40Availability(entry.runtime_data)])


class P40Availability(P40Entity, SwitchEntity):
    _attr_translation_key = "charging_availability"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "charging_availability")

    @property
    def available(self):
        return self.coordinator.last_update_success and self.coordinator.data.live.get(
            "charging_state"
        ) in {"UNAVAILABLE", "IDLE", "READY_FOR_CHARGING", "CHARGING", "SUSPENDED"}

    @property
    def is_on(self):
        state = self.coordinator.data.live.get("charging_state")
        return state != "UNAVAILABLE" if self.available else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_control("enable")

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_control("disable")
