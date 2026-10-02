"""The integration at work: pushing inputs, throttling, refilling a box."""

from datetime import timedelta

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.xy_scope.const import DOMAIN, THROTTLE_SECONDS

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
OPTIONS = {
    "inside_temp": "sensor.inside",
    "outside_temp": "weather.home",
    "weather": "weather.home",
    "car_a": "sensor.car",
    "power_switch": "light.outlet",
}


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    hass.config.latitude, hass.config.longitude = 49.2, -123.1
    hass.states.async_set("sensor.inside", "21.46")
    hass.states.async_set("weather.home", "rainy", {"temperature": 9.0})
    hass.states.async_set("sensor.car", "x", {"latitude": 49.25, "longitude": -123.1})
    hass.states.async_set("light.outlet", "on")

    async def forecasts(call) -> ServiceResponse:
        entities = call.data["entity_id"]
        if isinstance(entities, str):
            entities = [entities]
        return {e: {"forecast": [
            {"temperature": 9 + h, "precipitation_probability": 10 * h}
            for h in range(30)]} for e in entities}

    hass.services.async_register("weather", "get_forecasts", forecasts,
                                 supports_response=SupportsResponse.ONLY)
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options=OPTIONS)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


async def test_initial_push_has_every_input(hass, entry, box):
    assert len(box.pushes) == 1
    first = box.pushes[0]
    assert first["inside_temp"] == 21.46
    assert first["outside_temp"] == 9.0          # a weather entity's attribute
    assert first["car_a"] == {"lat": 49.25, "lon": -123.1}
    assert first["location"] == {"lat": 49.2, "lon": -123.1}
    assert first["forecast_temp"] == [9 + h for h in range(24)]
    assert first["forecast_rain"][:3] == [0, 10, 20]
    # Owned but unmapped inputs are cleared on the box.
    assert "high_temp" in first and first["high_temp"] is None
    assert "high_temp" not in box.inputs


async def test_changes_are_throttled_and_coalesced(hass, entry, box):
    box.pushes.clear()
    hass.states.async_set("sensor.inside", "22")
    await hass.async_block_till_done()
    # The initial push just went out, so this waits out the window...
    assert box.pushes == []
    hass.states.async_set("sensor.inside", "23")
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=THROTTLE_SECONDS + 1))
    await hass.async_block_till_done()
    # ...and then only the latest value goes.
    assert box.pushes == [{"inside_temp": 23.0}]


async def test_unavailable_entity_clears_its_input(hass, entry, box):
    hass.states.async_set("sensor.inside", "unavailable")
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=THROTTLE_SECONDS + 1))
    await hass.async_block_till_done()
    assert "inside_temp" not in box.inputs


async def test_restarted_box_is_refilled(hass, entry, box):
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.xy_scope_screen", "option": "home"}, blocking=True)
    assert box.screen == "home"
    # The box restarts and comes back empty, showing its default screen.
    box.boot, box.inputs, box.screen = "boot-2", {}, "clock"
    box.pushes.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert box.inputs["inside_temp"] == 21.46
    assert box.screen == "home"


async def test_box_back_after_outage_is_refilled(hass, entry, box):
    box.down = True
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert hass.states.get("select.xy_scope_screen").state == "unavailable"
    box.down = False
    box.pushes.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=4))
    await hass.async_block_till_done()
    assert box.pushes and "inside_temp" in box.pushes[0]
    assert hass.states.get("select.xy_scope_screen").state == "clock"


async def test_entities(hass, entry, box):
    select = hass.states.get("select.xy_scope_screen")
    assert select.state == "clock"
    assert select.attributes["options"] == ["home", "clock", "weather", "welcome"]
    assert hass.states.get("number.xy_scope_scale").attributes["max"] == 0.63
    assert hass.states.get("sensor.xy_scope_output").state == "playing"
    assert hass.states.get("sensor.xy_scope_frame_rate").state == "50.0"
    assert int(hass.states.get("sensor.xy_scope_inputs").state) >= 5

    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.xy_scope_scale", "value": 0.5}, blocking=True)
    assert box.scale == 0.5


async def test_power_switch_wraps_the_outlet(hass, entry, box):
    assert hass.states.get("switch.xy_scope_display_power").state == "on"
    # A smart plug exposed as a light; mocked so the call can be seen.
    calls = async_mock_service(hass, "light", "turn_off")
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.xy_scope_display_power"}, blocking=True)
    assert [c.data["entity_id"] for c in calls] == ["light.outlet"]
    hass.states.async_set("light.outlet", "off")
    await hass.async_block_till_done()
    assert hass.states.get("switch.xy_scope_display_power").state == "off"


async def test_bad_token_starts_reauth(hass, entry, box):
    box.token_ok = False
    hass.states.async_set("sensor.inside", "25")
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=THROTTLE_SECONDS + 1))
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_feeding_waits_for_home_assistant_to_start(hass: HomeAssistant, box):
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    hass.set_state(CoreState.starting)
    hass.states.async_set("sensor.inside", "20")
    e = MockConfigEntry(domain=DOMAIN, data=DATA,
                        options={"inside_temp": "sensor.inside"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert box.pushes == []
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert box.pushes[0]["inside_temp"] == 20.0
