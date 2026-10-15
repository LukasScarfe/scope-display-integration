"""The Superintendent's face: the mood is held, an animation plays per pick."""

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xy_scope.const import DOMAIN

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
MOOD = "select.xy_scope_face_mood"
ANIMATION = "select.xy_scope_face_animation"


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


async def pick(hass, entity, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity, "option": option},
        blocking=True)


async def test_the_boxs_moods_are_the_options_and_a_pick_is_pushed(
        hass, entry, box):
    state = hass.states.get(MOOD)
    assert state.attributes["options"] == ["neutral", "angry", "happy"]
    assert state.state == "neutral"
    await pick(hass, MOOD, "angry")
    assert box.pushes[-1] == {"super_mood": "angry"}
    assert hass.states.get(MOOD).state == "angry"


async def test_every_animation_pick_plays_even_the_same_twice(hass, entry, box):
    assert hass.states.get(ANIMATION).attributes["options"] == ["wink_left", "nod"]
    await pick(hass, ANIMATION, "wink_left")
    await pick(hass, ANIMATION, "wink_left")
    await pick(hass, ANIMATION, "nod")
    assert box.played == ["wink_left", "wink_left", "nod"]
