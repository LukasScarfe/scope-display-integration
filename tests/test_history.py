"""History series: the recorder read is stubbed, the plumbing around it is
real. (The harness's real-recorder fixture fails on Python 3.14.2, whose
`inspect` evaluates annotations the recorder only imports for type checking.
`resample` itself is tested in test_values.)"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xy_scope.const import DOMAIN

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}


async def test_history_series_are_even_and_end_now(hass: HomeAssistant, box):
    hass.config.components.add("recorder")
    now = dt_util.utcnow()
    asked = []

    def changes(hass_, start, end, entity_id, no_attributes, include_start_time_state):
        asked.append((entity_id, round((end - start) / timedelta(days=1))))
        # Shaped like the recorder's LazyState: no .domain.
        old = SimpleNamespace(entity_id=entity_id, state="30", attributes={},
                              last_changed=now - timedelta(days=3))
        new = SimpleNamespace(entity_id=entity_id, state="55", attributes={},
                              last_changed=now - timedelta(hours=1))
        return {entity_id: [old, new]}

    hass.states.async_set("sensor.ficus", "55")
    hass.states.async_set("sensor.inside", "21")
    recorder = SimpleNamespace(async_add_executor_job=hass.async_add_executor_job)
    with patch("homeassistant.components.recorder.get_instance",
               return_value=recorder), \
         patch("homeassistant.components.recorder.history."
               "state_changes_during_period", changes):
        entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={
            "plant_a": "sensor.ficus", "inside_temp": "sensor.inside"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        # The feeder starts as a background task (history can be slow).
        await hass.async_block_till_done(wait_background_tasks=True)

    assert sorted(asked) == [("sensor.ficus", 14), ("sensor.inside", 7)]
    plant = box.pushes[0]["plant_a"]
    week = box.pushes[0]["inside_week"]
    assert len(plant) == 14 * 12 and len(week) == 7 * 24
    assert plant[0] is None and plant[-1] == 55.0
    assert 30.0 in plant
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_failing_source_does_not_stop_the_push(hass: HomeAssistant, box):
    hass.config.components.add("recorder")
    hass.states.async_set("sensor.inside", "21")
    with patch("homeassistant.components.recorder.get_instance",
               side_effect=RuntimeError("recorder broke")):
        entry = MockConfigEntry(domain=DOMAIN, data=DATA,
                                options={"inside_temp": "sensor.inside"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert box.pushes[0]["inside_temp"] == 21.0
    await hass.config_entries.async_unload(entry.entry_id)
