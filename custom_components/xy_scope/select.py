"""The screen the display shows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from . import ScopeConfigEntry
from .api import ScopeError
from .const import LOGGER, MANUAL_HOLD
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
    to the box shows up here without an integration update.

    A pick made by a person holds for MANUAL_HOLD. Without the hold, a
    timetable automation stepping the screens would replace it at its next
    tick, maybe seconds later. A person's pick is told apart by its context:
    a call from the frontend, the app or voice carries the user, one from an
    automation does not. Automation picks during the hold are not dropped:
    the newest goes out when the hold ends, so the timetable carries on."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "screen")
        self._data = entry.runtime_data
        self._held_until: datetime | None = None
        self._pending: str | None = None
        self._release: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_release)

    @property
    def options(self) -> list[str]:
        return [s["name"] for s in self.coordinator.data.get("screens", [])]

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("screen")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"held_until": self._held_until.isoformat()
                if self._held_until else None}

    async def async_select_option(self, option: str) -> None:
        if self._context is not None and self._context.user_id is not None:
            self._pending = None
            await self._show(option)
            self._hold()
        elif self._held_until is not None:
            self._pending = option
        else:
            await self._show(option)

    async def _show(self, option: str) -> None:
        try:
            status = await self._data.client.put_screen(screen=option)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not change the screen: {err}") from err
        self._data.feeder.last_screen = option
        self.coordinator.push_result(status)

    def _hold(self) -> None:
        self._cancel_release()
        self._held_until = dt_util.utcnow() + MANUAL_HOLD
        self._release = async_call_later(self.hass, MANUAL_HOLD, self._released)
        self.async_write_ha_state()

    def _cancel_release(self) -> None:
        if self._release is not None:
            self._release()
            self._release = None

    async def _released(self, _now: datetime) -> None:
        self._release = None
        self._held_until = None
        pending, self._pending = self._pending, None
        if pending is not None and pending != self.current_option:
            try:
                await self._show(pending)
            except HomeAssistantError as err:
                LOGGER.warning("%s", err)
        self.async_write_ha_state()
