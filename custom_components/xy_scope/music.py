"""Oscilloscope music: the box draws a track, a speaker plays it.

The box's music screen is a track played straight into the scope -- the
sound *is* the picture. For it to be heard too, the same file goes to a media
player of your choosing, and the scope is started at the speaker's own
position once it is playing, so the two line up.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import ScopeClient, ScopeError
from .const import (
    DOMAIN, LOGGER, MUSIC_SCREEN, REALIGN_AFTER, REALIGN_TOLERANCE,
    SPEAKER_START_TIMEOUT,
)
from .coordinator import ScopeCoordinator


class Music:
    """Plays one track at a time: on the scope, and on the chosen speaker."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: ScopeClient,
        coordinator: ScopeCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.coordinator = coordinator
        self.speaker: str | None = None     # a media_player entity id
        self.delay = 0.0                    # s the speaker's sound runs late
        self._playing_on: str | None = None
        self._track: str | None = None
        self._realign = None

    def seconds(self, track: str) -> float | None:
        for t in self.coordinator.data.get("tracks") or []:
            if isinstance(t, dict) and t.get("name") == track:
                return float(t.get("seconds") or 0)
        return None

    async def play(self, track: str) -> float:
        """Start `track` on the speaker (if one is chosen) and the scope, in
        step. Returns how many seconds of it are left to play."""
        length = self.seconds(track)
        if length is None:
            raise HomeAssistantError(f"The box has no track {track!r}")
        self._cancel_realign()
        at = 0.0
        speaker = self.speaker
        if speaker:
            try:
                at = await self._start_speaker(speaker, track)
            except HomeAssistantError as err:
                # The picture still plays; it is only silent.
                LOGGER.warning("Could not play %s on %s: %s", track, speaker, err)
                speaker = None
        self._playing_on, self._track = speaker, track
        at = max(0.0, at - self.delay)
        await self._cue(track, at)
        if speaker:
            self._realign = async_call_later(
                self.hass, REALIGN_AFTER, self._realign_now)
        return max(0.0, length - at)

    async def stop(self) -> None:
        """Another screen took over: stop the speaker if it is still ours."""
        self._cancel_realign()
        speaker, self._playing_on, self._track = self._playing_on, None, None
        if not speaker:
            return
        state = self.hass.states.get(speaker)
        if state is None or state.state != "playing":
            return
        try:
            await self.hass.services.async_call(
                "media_player", "media_stop", {"entity_id": speaker},
                blocking=True)
        except HomeAssistantError as err:
            LOGGER.warning("Could not stop %s: %s", speaker, err)

    def finished(self) -> None:
        """The song ran out by itself; the speaker stopped with it."""
        self._cancel_realign()
        self._playing_on = self._track = None

    async def _cue(self, track: str, at: float) -> None:
        try:
            status = await self.client.put_screen(
                screen=MUSIC_SCREEN, track=track, at=at, once=True)
        except ScopeError as err:
            raise HomeAssistantError(f"Could not play {track}: {err}") from err
        self.coordinator.push_result(status)

    async def _start_speaker(self, speaker: str, track: str) -> float:
        """Play the track on the speaker and wait until it is really playing;
        returns its position then, which is where the scope should start."""
        asked = dt_util.utcnow()
        await self.hass.services.async_call(
            "media_player", "play_media",
            {"entity_id": speaker,
             "media_content_id": self.client.track_url(track),
             "media_content_type": "music"},
            blocking=True)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SPEAKER_START_TIMEOUT
        while loop.time() < deadline:
            pos = self._speaker_position(speaker, since=asked)
            if pos is not None:
                return pos
            await asyncio.sleep(0.2)
        raise HomeAssistantError("it did not start playing")

    def _speaker_position(self, speaker: str, since: datetime | None = None
                          ) -> float | None:
        """Where the speaker is in its track right now, from its last
        reported position; None until it plays and has reported one (after
        `since`, so a position left from the previous track is not taken)."""
        state = self.hass.states.get(speaker)
        if state is None or state.state != "playing":
            return None
        pos = state.attributes.get("media_position")
        at = state.attributes.get("media_position_updated_at")
        if pos is None:
            return None
        if isinstance(at, str):
            at = dt_util.parse_datetime(at)
        if not isinstance(at, datetime):
            return float(pos)
        if since is not None and at < since:
            return None
        return float(pos) + (dt_util.utcnow() - at).total_seconds()

    async def _realign_now(self, _now: datetime) -> None:
        """The speaker's position settles once it is going: if the scope has
        drifted from it, start the scope again where the speaker is."""
        self._realign = None
        speaker, track = self._playing_on, self._track
        if not speaker or not track:
            return
        pos = self._speaker_position(speaker)
        if pos is None:
            return
        try:
            status = await self.client.status()
        except ScopeError:
            return
        music: dict[str, Any] = status.get("music") or {}
        if music.get("track") != track or music.get("pos") is None:
            return      # the scope moved on: nothing to line up
        target = max(0.0, pos - self.delay)
        if abs(float(music["pos"]) - target) > REALIGN_TOLERANCE:
            LOGGER.debug("%s: scope %.2fs, speaker %.2fs; lining up",
                         DOMAIN, music["pos"], target)
            try:
                await self._cue(track, target)
            except HomeAssistantError as err:
                LOGGER.warning("%s", err)

    def _cancel_realign(self) -> None:
        if self._realign is not None:
            self._realign()
            self._realign = None
