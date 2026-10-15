"""The screen the display shows, and the music it can play."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import ScopeConfigEntry
from .api import ScopeError
from .const import LOGGER, MANUAL_HOLD, MUSIC_GRACE, MUSIC_SCREEN, NO_SPEAKER
from .entity import ScopeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScopeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [ScreenSelect(entry), MusicSelect(entry), SpeakerSelect(entry),
         MoodSelect(entry), AnimationSelect(entry)])


class ScreenSelect(ScopeEntity, SelectEntity):
    """Options are the box's own screen names (`home`, `weather`, ...), so
    automations name a screen the same way the box does, and a screen added
    to the box shows up here without an integration update.

    A pick made by a person holds for MANUAL_HOLD. Without the hold, a
    timetable automation stepping the screens would replace it at its next
    tick, maybe seconds later. A person's pick is told apart by its context:
    a call from the frontend, the app or voice carries the user, one from an
    automation does not. Automation picks during the hold are not dropped:
    the newest goes out when the hold ends, so the timetable carries on.

    Music holds the same way, for the rest of the song, whoever picked it:
    the song plays to its end and the timetable resumes after it. A person
    picking another screen ends it early."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "screen")
        self._data = entry.runtime_data
        self._held_until: datetime | None = None
        self._pending: str | None = None
        self._release: CALLBACK_TYPE | None = None
        self._song = False      # the hold is a song's

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._data.screen = self
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
        if option == MUSIC_SCREEN:
            # The music screen itself plays the box's current track.
            data = self.coordinator.data
            names = [t.get("name") for t in data.get("tracks") or []]
            track = data.get("track") if data.get("track") in names else (
                names[0] if names else None)
            if not track:
                raise HomeAssistantError("The box has no music tracks")
            await self.play_music(track)
        elif self._context is not None and self._context.user_id is not None:
            self._pending = None
            if self._song:
                self._song = False
                await self._data.music.stop()
            await self._show(option)
            self._hold(MANUAL_HOLD)
        elif self._held_until is not None:
            self._pending = option
        else:
            await self._show(option)

    async def play_music(self, track: str) -> None:
        """Play a track to its end, holding off the timetable meanwhile. The
        timetable's picks during the song stay pending, so the screen goes
        back into the rotation as soon as it is over."""
        left = await self._data.music.play(track)
        self._data.feeder.last_screen = MUSIC_SCREEN
        self._song = True
        self._hold(timedelta(seconds=left) + MUSIC_GRACE)

    async def _show(self, option: str) -> None:
        try:
            status = await self._data.client.put_screen(screen=option)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not change the screen: {err}") from err
        self._data.feeder.last_screen = option
        self.coordinator.push_result(status)

    def _hold(self, length: timedelta) -> None:
        self._cancel_release()
        self._held_until = dt_util.utcnow() + length
        self._release = async_call_later(self.hass, length, self._released)
        self.async_write_ha_state()

    def _cancel_release(self) -> None:
        if self._release is not None:
            self._release()
            self._release = None

    async def _released(self, _now: datetime) -> None:
        self._release = None
        self._held_until = None
        if self._song:
            # The box went back to the screen from before by itself; see
            # where it is before deciding what to push.
            self._song = False
            self._data.music.finished()
            await self.coordinator.async_refresh()
        pending, self._pending = self._pending, None
        if pending is not None and pending != self.current_option:
            try:
                await self._show(pending)
            except HomeAssistantError as err:
                LOGGER.warning("%s", err)
        self.async_write_ha_state()


class MusicSelect(ScopeEntity, SelectEntity):
    """The box's music tracks. Picking one plays it, start to finish, on the
    scope and the chosen speaker; then the screens carry on."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "music")
        self._data = entry.runtime_data

    @property
    def options(self) -> list[str]:
        return [t["name"] for t in self.coordinator.data.get("tracks") or []
                if isinstance(t, dict) and t.get("name")]

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data.get("screen") != MUSIC_SCREEN:
            return None
        return self.coordinator.data.get("track")

    async def async_select_option(self, option: str) -> None:
        if self._data.screen is None:
            raise HomeAssistantError("The screen select is not ready yet")
        await self._data.screen.play_music(option)


class SpeakerSelect(ScopeEntity, SelectEntity, RestoreEntity):
    """Which media player the music is heard on, or none: the scope alone.
    Listed by name; players that are unavailable are left out."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "speaker")
        self._music = entry.runtime_data.music

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state != NO_SPEAKER:
            self._music.speaker = last.attributes.get("entity_id") or (
                self._players().get(last.state))

    def _players(self) -> dict[str, str]:
        """Name -> entity id of every media player that is there now, plus
        the chosen one even while it is away, so the choice survives."""
        found: dict[str, str] = {}
        for state in self.hass.states.async_all("media_player"):
            if state.state == "unavailable" and (
                    state.entity_id != self._music.speaker):
                continue
            name = state.name
            if name in found or name == NO_SPEAKER:
                name = f"{name} ({state.entity_id})"
            found[name] = state.entity_id
        return found

    @property
    def options(self) -> list[str]:
        return [NO_SPEAKER, *sorted(self._players())]

    @property
    def current_option(self) -> str | None:
        for name, entity_id in self._players().items():
            if entity_id == self._music.speaker:
                return name
        return NO_SPEAKER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"entity_id": self._music.speaker}

    async def async_select_option(self, option: str) -> None:
        self._music.speaker = (
            None if option == NO_SPEAKER else self._players().get(option))
        self.async_write_ha_state()


class MoodSelect(ScopeEntity, SelectEntity):
    """The Superintendent's mood: what he is, held until changed, with the
    lids springing from one mood to the next. Options are the box's own, so
    a mood added there shows up here without an integration update. Sent as
    the box's `super_mood` input."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "mood")
        self._data = entry.runtime_data

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.data.get("moods") or [])

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("mood")

    async def async_select_option(self, option: str) -> None:
        try:
            status = await self._data.client.put_inputs({"super_mood": option})
        except ScopeError as err:
            raise HomeAssistantError(f"Could not set the mood: {err}") from err
        self.coordinator.push_result(status)


class AnimationSelect(ScopeEntity, SelectEntity):
    """Something the Superintendent does, then stops doing: a wink, a look
    round. Picking one plays it once over his mood -- picking the same one
    again plays it again -- queued behind any playing. Its state is the one
    playing as of the last poll, if any."""

    def __init__(self, entry: ScopeConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, "animation")
        self._data = entry.runtime_data

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.data.get("animations") or [])

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("animation")

    async def async_select_option(self, option: str) -> None:
        try:
            status = await self._data.client.put_screen(play=option)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not play {option}: {err}") from err
        self.coordinator.push_result(status)
