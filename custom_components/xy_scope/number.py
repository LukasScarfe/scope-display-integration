"""The display's scale: how much of the tube the picture fills."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ScopeConfigEntry
from .api import ScopeError
from .entity import ScopeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScopeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ScaleNumber(entry)])


class ScaleNumber(ScopeEntity, NumberEntity):
    """0..1 of full deflection, capped at the maximum calibrated on the box
    (its web page's scale graticule), so HA can shrink the picture but never
    drive it past what was found to look clean."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.05
    _attr_native_step = 0.01

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "scale")
        self._client = entry.runtime_data.client

    @property
    def native_max_value(self) -> float:
        return float(self.coordinator.data.get("max_scale") or 1.0)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("scale")

    async def async_set_native_value(self, value: float) -> None:
        try:
            status = await self._client.put_screen(scale=value)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not set the scale: {err}") from err
        self.coordinator.push_result(status)
