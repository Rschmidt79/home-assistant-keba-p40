"""Common device identity and coordinator availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import P40Coordinator


class P40Entity(CoordinatorEntity[P40Coordinator]):
    """Group all entities under the authoritative serial number."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: P40Coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.serial}_{key}"
        data = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            manufacturer="KEBA",
            model=data.live.get("model") or data.device.get("model"),
            name=data.device.get("rest_alias") or f"KEBA P40 {coordinator.serial}",
            serial_number=coordinator.serial,
            sw_version=data.device.get("package_version"),
            hw_version=data.device.get("hardware_revision"),
        )

    def value(self):
        """Read an explicitly parsed value; missing values remain unknown."""
        data = self.coordinator.data
        for section in (data.live, data.session, data.configuration, data.device):
            if self._key in section:
                return section[self._key]
        return None

    @property
    def available(self) -> bool:
        return super().available and self.value() is not None
