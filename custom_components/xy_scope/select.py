"""The screen the display shows."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    async_add_entities([ScreenSelect(entry)])


class ScreenSelect(ScopeEntity, SelectEntity):
    """Options are the box's own screen names (`home`, `weather`, ...), so
    automations name a screen the same way the box does, and a screen added
    to the box shows up here without an integration update."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "screen")
        self._data = entry.runtime_data

    @property
    def options(self) -> list[str]:
        return [s["name"] for s in self.coordinator.data.get("screens", [])]

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("screen")

    async def async_select_option(self, option: str) -> None:
        try:
            status = await self._data.client.put_screen(screen=option)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not change the screen: {err}") from err
        self._data.feeder.last_screen = option
        self.coordinator.push_result(status)
