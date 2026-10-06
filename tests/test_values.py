"""The value conversions, without Home Assistant running."""

from datetime import datetime, timedelta, timezone

from homeassistant.core import State

from custom_components.xy_scope.feeder import (
    resample,
    state_location,
    state_number,
    state_titles,
)

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _state(value, minutes, entity="sensor.x", attrs=None):
    s = State(entity, value, attrs or {})
    s.last_changed = T0 + timedelta(minutes=minutes)
    return s


def test_resample_holds_the_last_reading():
    states = [_state("10", -30), _state("12", 90), _state("bad", 150),
              _state("14", 200)]
    got = resample(states, T0, timedelta(hours=1), 4)
    # At 1 h: 10 still; 2 h: 12; 3 h: not a number; 4 h: 14.
    assert got == [10.0, 12.0, None, 14.0]


def test_resample_before_any_state_is_none():
    assert resample([_state("5", 150)], T0, timedelta(hours=1), 3) == [None, None, 5.0]


def test_state_number():
    assert state_number(State("sensor.t", "21.456")) == 21.46
    assert state_number(State("sensor.t", "unavailable")) is None
    assert state_number(State("sensor.t", "nan")) is None
    assert state_number(State("weather.w", "sunny", {"temperature": 7})) == 7.0
    assert state_number(None) is None


def test_state_location():
    assert state_location(State("sensor.c", "x", {"latitude": "1.5",
                                                  "longitude": 2})) == {
        "lat": 1.5, "lon": 2.0}
    assert state_location(State("sensor.c", "x", {})) is None


def test_state_titles():
    assert state_titles(State("sensor.b", "2", {"titles": [" Tim birthday ", 3, ""]})) == [
        "Tim birthday"]
    assert state_titles(State("sensor.b", "0", {"titles": []})) == []
    assert state_titles(State("sensor.b", "0", {})) is None
    assert state_titles(State("sensor.b", "unavailable", {"titles": ["x"]})) is None
