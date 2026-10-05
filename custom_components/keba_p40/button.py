"""Explicit start/stop actions. Never invoked by setup or polling."""

from homeassistant.components.button import ButtonEntity

from .entity import P40Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [P40ChargingButton(entry.runtime_data, action) for action in ("start", "stop")]
    )


class P40ChargingButton(P40Entity, ButtonEntity):
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, action):
        super().__init__(coordinator, f"{action}_charging")
        self._action = action
        self._attr_translation_key = f"{action}_charging"

    @property
    def available(self):
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.live.get("charging_state") is not None
        )

    async def async_press(self):
        await self.coordinator.async_control(self._action)
