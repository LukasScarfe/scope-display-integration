"""The shared base for the display's entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ScopeCoordinator


class ScopeEntity(CoordinatorEntity[ScopeCoordinator]):
    """An entity of the one display device a config entry describes."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ScopeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="XY Scope",
            manufacturer="xy-bench",
            model="Oscilloscope vector display",
            configuration_url=coordinator.client.base,
        )
