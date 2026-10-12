"""The display's scale, and how late the music speaker runs."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity, NumberMode, RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTime
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
    async_add_entities([ScaleNumber(entry), SpeakerDelayNumber(entry)])


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


class SpeakerDelayNumber(ScopeEntity, RestoreNumber):
    """How much later the music speaker's sound comes out than the position
    it reports -- buffering a speaker does not own up to. The scope is held
    back by this much so picture and sound land together; nudge it until they
    do. Negative if the sound comes early."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -5.0
    _attr_native_max_value = 5.0
    _attr_native_step = 0.05
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "speaker_delay")
        self._music = entry.runtime_data.music

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._music.delay = float(last.native_value)

    @property
    def native_value(self) -> float:
        return self._music.delay

    async def async_set_native_value(self, value: float) -> None:
        self._music.delay = value
        self.async_write_ha_state()
