"""The screen select: a person's pick holds; automations wait their turn."""

from datetime import timedelta

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.xy_scope.const import DOMAIN, MANUAL_HOLD

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
SELECT = "select.xy_scope_screen"


@pytest.fixture
def someone(hass_admin_user):
    return hass_admin_user.id


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


async def pick(hass, option, user=None):
    # A person's call carries their user id; an automation's does not.
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": option},
        blocking=True, context=Context(user_id=user))


async def later(hass, seconds):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_automation_picks_go_straight_out(hass, entry, box):
    await pick(hass, "weather")
    await pick(hass, "home")
    assert box.screens_set == ["weather", "home"]
    assert hass.states.get(SELECT).attributes["held_until"] is None


async def test_a_persons_pick_holds_then_the_newest_automation_pick_goes_out(
        hass, entry, box, someone):
    await pick(hass, "weather", user=someone)
    assert hass.states.get(SELECT).state == "weather"
    assert hass.states.get(SELECT).attributes["held_until"] is not None

    await pick(hass, "home")             # the timetable ticks during the hold
    await pick(hass, "welcome")
    assert box.screens_set == ["weather"]
    assert hass.states.get(SELECT).state == "weather"

    await later(hass, MANUAL_HOLD.total_seconds() + 1)
    assert box.screens_set == ["weather", "welcome"]
    assert hass.states.get(SELECT).state == "welcome"
    assert hass.states.get(SELECT).attributes["held_until"] is None


async def test_a_hold_with_no_automation_pick_leaves_the_screen(hass, entry, box, someone):
    await pick(hass, "weather", user=someone)
    await later(hass, MANUAL_HOLD.total_seconds() + 1)
    assert box.screens_set == ["weather"]
    await pick(hass, "home")             # and automations are back in charge
    assert box.screens_set == ["weather", "home"]


async def test_a_second_person_pick_restarts_the_hold(hass, entry, box, someone):
    await pick(hass, "weather", user=someone)
    await later(hass, 40)
    await pick(hass, "home", user=someone)
    await pick(hass, "welcome")
    await later(hass, 30)                # 70 s after the first pick, 30 after the second
    assert box.screens_set == ["weather", "home"]
    await later(hass, 60)
    assert box.screens_set == ["weather", "home", "welcome"]
