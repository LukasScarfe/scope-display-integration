"""Music: a picked track plays to its end on the scope and the chosen
speaker, holding off the screen timetable, which carries on after it."""

from datetime import timedelta

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.xy_scope import music
from custom_components.xy_scope.const import DOMAIN, MUSIC_GRACE

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
SCREEN = "select.xy_scope_screen"
MUSIC = "select.xy_scope_music"
SPEAKER = "select.xy_scope_music_speaker"
DELAY = "number.xy_scope_speaker_delay"
PLAYER = "media_player.bedroom_speaker"


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


@pytest.fixture
def speaker(hass):
    """A media player that starts playing, 2 s in, when asked to."""
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Bedroom speaker"})
    played: list[ServiceCall] = []

    async def play_media(call: ServiceCall) -> None:
        played.append(call)
        hass.states.async_set(PLAYER, "playing", {
            "friendly_name": "Bedroom speaker", "media_position": 2.0,
            "media_position_updated_at": dt_util.utcnow()})

    hass.services.async_register("media_player", "play_media", play_media)
    stops = async_mock_service(hass, "media_player", "media_stop")
    return played, stops


async def select(hass, entity, option, user=None):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity, "option": option},
        blocking=True, context=Context(user_id=user))


async def later(hass, seconds):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_tracks_are_the_boxs(hass, entry):
    assert hass.states.get(MUSIC).attributes["options"] == ["Planets", "Blocks"]
    assert hass.states.get(SPEAKER).state == "Scope only"


async def test_a_song_holds_the_rotation_to_its_end(hass, entry, box):
    await select(hass, MUSIC, "Blocks")
    assert box.cues == [("Blocks", 0.0, True)]
    assert hass.states.get(SCREEN).state == "music"
    assert hass.states.get(MUSIC).state == "Blocks"

    await select(hass, SCREEN, "weather")        # the timetable ticks
    await later(hass, 120)
    await select(hass, SCREEN, "home")
    assert box.screens_set == ["music"]          # ...but the song plays on

    box.screen = "clock"                         # the box went back by itself
    await later(hass, 213 + MUSIC_GRACE.total_seconds())
    assert box.screens_set == ["music", "home"]  # and the rotation resumes
    assert hass.states.get(SCREEN).attributes["held_until"] is None


async def test_the_speaker_plays_and_the_scope_starts_where_it_is(
        hass, entry, box, speaker):
    played, _ = speaker
    await select(hass, SPEAKER, "Bedroom speaker")
    await hass.services.async_call(
        "number", "set_value", {"entity_id": DELAY, "value": 0.5}, blocking=True)
    await select(hass, MUSIC, "Planets")
    assert played[0].data["media_content_id"] == "http://box:8080/music/Planets.wav"
    track, at, once = box.cues[0]
    assert (track, once) == ("Planets", True)
    assert at == pytest.approx(1.5, abs=0.1)     # 2 s in, less the delay


async def test_a_person_picking_a_screen_ends_the_song(
        hass, entry, box, speaker, hass_admin_user):
    _, stops = speaker
    await select(hass, SPEAKER, "Bedroom speaker")
    await select(hass, MUSIC, "Planets")
    await select(hass, SCREEN, "weather", user=hass_admin_user.id)
    assert box.screens_set == ["music", "weather"]
    assert [c.data["entity_id"] for c in stops] == [PLAYER]


async def test_a_speaker_that_never_starts_leaves_the_scope_playing(
        hass, entry, box, monkeypatch):
    monkeypatch.setattr(music, "SPEAKER_START_TIMEOUT", 0.3)
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Bedroom speaker"})
    async_mock_service(hass, "media_player", "play_media")
    await select(hass, SPEAKER, "Bedroom speaker")
    await select(hass, MUSIC, "Planets")
    assert box.cues == [("Planets", 0.0, True)]
    assert hass.states.get(SCREEN).state == "music"


async def test_picking_the_music_screen_plays_the_current_track(hass, entry, box):
    await select(hass, SCREEN, "music")
    assert box.cues == [("Planets", 0.0, True)]
    assert hass.states.get(SCREEN).attributes["held_until"] is not None
