"""Display power, as a switch wrapping the scope's own outlet, and whether
a screen plays its transition backwards on the way out.

Off has to mean the outlet: stopping the signal would park the beam on one
spot and burn the phosphor. Wrapping it here lets automations talk to one
device for everything about the display.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.const import EntityCategory
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import ScopeConfigEntry
from .api import ScopeError
from .const import DOMAIN, OPT_POWER
from .entity import ScopeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScopeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entities: list[SwitchEntity] = [OutroSwitch(entry)]
    if outlet := entry.options.get(OPT_POWER):
        entities.append(DisplayPowerSwitch(entry, outlet))
    async_add_entities(entities)


class DisplayPowerSwitch(SwitchEntity):
    """Mirrors the outlet's state; on and off are passed through to it."""

    _attr_has_entity_name = True
    _attr_translation_key = "power"
    _attr_should_poll = False

    def __init__(self, entry: ScopeConfigEntry, outlet: str) -> None:
        self._outlet = outlet
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_extra_state_attributes = {"outlet": outlet}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_track_state_change_event(
            self.hass, [self._outlet], self._outlet_changed))

    @callback
    def _outlet_changed(self, event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        state = self.hass.states.get(self._outlet)
        return state is not None and state.state not in (
            STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def is_on(self) -> bool | None:
        state = self.hass.states.get(self._outlet)
        return None if state is None else state.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._call("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._call("turn_off")

    async def _call(self, service: str) -> None:
        await self.hass.services.async_call(
            self._outlet.split(".", 1)[0], service,
            {"entity_id": self._outlet}, blocking=True, context=self._context)


class OutroSwitch(ScopeEntity, SwitchEntity):
    """On, the screen going away first plays the transition style backwards
    (zooms out, slides off, fades); off, the next one just comes in."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "outro")
        self._data = entry.runtime_data

    @property
    def available(self) -> bool:
        return super().available and "outro" in self.coordinator.data

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("outro")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        try:
            status = await self._data.client.put_screen(outro=on)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not set the exit: {err}") from err
        self.coordinator.push_result(status)
