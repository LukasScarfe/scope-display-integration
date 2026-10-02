"""First guesses for the options: which entity feeds each screen input.

Found by device class, domain and a few name keywords on whatever Home
Assistant this is installed in -- never by entity id, since every home names
things differently. Guesses only: the options form shows them pre-filled and
every one can be changed or cleared.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .const import (
    OPT_CAR_A,
    OPT_CAR_B,
    OPT_HIGH_TEMP,
    OPT_INSIDE_TEMP,
    OPT_LOW_TEMP,
    OPT_OUTSIDE_TEMP,
    OPT_PLANT_A,
    OPT_PLANT_B,
    OPT_POWER,
    OPT_WEATHER,
)

# Integrations whose sensors describe the weather outside.
WEATHER_PLATFORMS = {
    "accuweather", "buienradar", "ecowitt", "environment_canada", "met",
    "met_eireann", "meteo_france", "netatmo", "nws", "openweathermap",
    "pirateweather", "smhi", "tomorrowio", "weatherflow", "weatherkit",
}
# WeatherEntityFeature.FORECAST_HOURLY
FORECAST_HOURLY = 2

_OUTSIDE = ("outside", "outdoor", "exterior", "external", "garden", "balcony")
_INSIDE_STRONG = ("living", "inside", "indoor", "lounge", "family")
_INSIDE_WEAK = ("room", "bedroom", "office", "kitchen", "hall", "shelf")
# Readings that are a temperature but not the air's: chips, batteries, probes,
# or derived weather figures.
_NOT_AIR = ("cpu", "chip", "processor", "device", "battery", "motion",
            "soil", "water", "fridge", "freezer", "oven", "probe", "dew",
            "feels", "apparent", "humidex", "chill", "heat_index", "target",
            "setpoint", "forecast")
_HIGH = ("high", "max")
_LOW = ("low", "min")
_CAR = ("car", "park", "vehicle")
_SCOPE = ("scope",)


def _words(state: State) -> str:
    name = str(state.attributes.get("friendly_name", ""))
    return re.sub(r"[^a-z0-9]+", "_", f"{state.entity_id} {name}".lower())


def _has(words: str, keys: tuple[str, ...]) -> bool:
    return any(k in words for k in keys)


def _numeric(state: State) -> bool:
    try:
        float(state.state)
    except (TypeError, ValueError):
        return False
    return True


def suggest_options(hass: HomeAssistant) -> dict[str, Any]:
    """Option values guessed from the entities this Home Assistant has."""
    reg = er.async_get(hass)

    def platform(entity_id: str) -> str | None:
        entry = reg.async_get(entity_id)
        return entry.platform if entry else None

    states = sorted(hass.states.async_all(), key=lambda s: s.entity_id)
    out: dict[str, Any] = {}

    temps = [s for s in states
             if s.domain == "sensor"
             and s.attributes.get("device_class") == "temperature"
             and _numeric(s)]
    air = [s for s in temps if not _has(_words(s), _NOT_AIR)]

    def outside_score(s: State) -> int:
        w = _words(s)
        if _has(w, _HIGH + _LOW):
            return 0
        score = 3 * _has(w, _OUTSIDE)
        score += 2 * (platform(s.entity_id) in WEATHER_PLATFORMS)
        return score

    def inside_score(s: State) -> int:
        w = _words(s)
        if _has(w, _OUTSIDE) or platform(s.entity_id) in WEATHER_PLATFORMS:
            return 0
        return 3 * _has(w, _INSIDE_STRONG) + _has(w, _INSIDE_WEAK)

    outside = _best(air, outside_score)
    inside = _best(air, inside_score)
    if outside:
        out[OPT_OUTSIDE_TEMP] = outside.entity_id
    if inside:
        out[OPT_INSIDE_TEMP] = inside.entity_id

    # High and low: from the same source as the outside reading, preferably.
    source = platform(outside.entity_id) if outside else None
    for opt, keys in ((OPT_HIGH_TEMP, _HIGH), (OPT_LOW_TEMP, _LOW)):
        pick = _best(temps, lambda s, keys=keys: (
            3 * _has(_words(s), keys)
            * (1 + (source is not None and platform(s.entity_id) == source))))
        if pick:
            out[opt] = pick.entity_id

    # The forecast: one with an hourly forecast, preferably from the source
    # that gave the high and low (a service that publishes those publishes a
    # real forecast), and not met.no, whose hourly forecast has no rain chance.
    if OPT_HIGH_TEMP in out:
        source = platform(out[OPT_HIGH_TEMP]) or source
    weathers = [s for s in states if s.domain == "weather"
                and int(s.attributes.get("supported_features") or 0)
                & FORECAST_HOURLY]
    weather = _best(weathers, lambda s: (
        2 + 2 * (source is not None and platform(s.entity_id) == source)
        - (platform(s.entity_id) == "met")))
    if weather:
        out[OPT_WEATHER] = weather.entity_id

    moisture = [s for s in states if s.domain == "sensor"
                and s.attributes.get("device_class") == "moisture"]
    for opt, s in zip((OPT_PLANT_A, OPT_PLANT_B), moisture):
        out[opt] = s.entity_id

    cars = [s for s in states
            if s.domain in ("sensor", "device_tracker")
            and "latitude" in s.attributes and "longitude" in s.attributes
            and _has(_words(s), _CAR)]
    for opt, s in zip((OPT_CAR_A, OPT_CAR_B), cars):
        out[opt] = s.entity_id

    power = _best([s for s in states if s.domain == "switch"],
                  lambda s: _has(_words(s), _SCOPE))
    if power:
        out[OPT_POWER] = power.entity_id
    return out


def _best(states: list[State], score) -> State | None:
    """The highest-scoring state, first wins ties; None if nothing scores."""
    best, best_score = None, 0
    for s in states:
        sc = score(s)
        if sc > best_score:
            best, best_score = s, sc
    return best
