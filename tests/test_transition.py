"""Screen transitions: the box's styles as a select, the exit as a switch."""

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xy_scope.const import DOMAIN

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
INTRO = "select.xy_scope_screen_transition"
OUTRO = "switch.xy_scope_transition_exit"


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


async def test_the_boxs_styles_are_the_options_and_a_pick_is_pushed(
        hass, entry, box):
    state = hass.states.get(INTRO)
    assert state.attributes["options"] == ["draw", "zoom", "morph", "random"]
    assert state.state == "draw"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": INTRO, "option": "morph"},
        blocking=True)
    assert box.intro == "morph"
    assert hass.states.get(INTRO).state == "morph"


async def test_the_exit_switch_sets_the_box(hass, entry, box):
    assert hass.states.get(OUTRO).state == "off"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": OUTRO}, blocking=True)
    assert box.outro is True
    assert hass.states.get(OUTRO).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": OUTRO}, blocking=True)
    assert box.outro is False


async def test_a_box_without_transitions_leaves_them_unavailable(hass, box):
    plain = box.status_dict
    box.status_dict = lambda: {k: v for k, v in plain().items()
                               if k not in ("intro", "outro", "intros")}
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(INTRO).state == "unavailable"
    assert hass.states.get(OUTRO).state == "unavailable"
