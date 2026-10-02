"""Keeps the box's inputs fresh from the entities mapped in the options.

The box holds named inputs; screens draw whichever they need. This watches each
mapped entity and pushes its input when it changes, at most once every
THROTTLE_SECONDS per input (changes in between are coalesced, the latest wins).
Some inputs are derived rather than read:

- the hourly forecast, fetched with `weather.get_forecasts` when the weather
  entity updates;
- history series (plants over 14 days, temperatures over 7), read from the
  recorder once an hour and resampled onto an even grid, oldest first, ending
  now -- the box never parses timestamps;
- the sun's times today (as local hours) and the home location, for the sky.

Every value pushed is also kept here, so a box that restarted or was away can
be refilled in one request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .api import ScopeAuthError, ScopeClient, ScopeError
from .const import (
    ALL_INPUTS,
    DOMAIN,
    FORECAST_HOURS,
    FORECAST_MIN_INTERVAL,
    HISTORY_INTERVAL,
    HISTORY_SERIES,
    IN_FORECAST_RAIN,
    IN_FORECAST_TEMP,
    IN_LOCATION,
    IN_SUN,
    LOCATION_INPUTS,
    LOGGER,
    NUMERIC_INPUTS,
    OPT_WEATHER,
    THROTTLE_SECONDS,
)
from .coordinator import ScopeCoordinator

SUN = "sun.sun"
RETRY_SECONDS = 30.0


def state_number(state: State | None) -> float | None:
    """A state as a number, or None when it is not a reading. A weather entity
    has a condition as its state; its temperature is an attribute."""
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    # entity_id, not .domain: the recorder's LazyState has no .domain.
    if state.entity_id.startswith("weather."):
        value: Any = state.attributes.get("temperature")
    else:
        value = state.state
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if math.isfinite(f) else None


def state_location(state: State | None) -> dict[str, float] | None:
    """{"lat", "lon"} from an entity's attributes, or None."""
    if state is None:
        return None
    try:
        lat = float(state.attributes["latitude"])
        lon = float(state.attributes["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"lat": round(lat, 5), "lon": round(lon, 5)}


def local_hours(value: Any) -> float | None:
    """A timestamp (string or datetime) as hours past local midnight."""
    when = dt_util.parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(when, datetime):
        return None
    when = dt_util.as_local(when)
    return round(when.hour + when.minute / 60 + when.second / 3600, 3)


def sun_input(state: State | None) -> dict[str, float | None] | None:
    """Today's sun for the box: rise, noon and set as local hours, and where
    it is now. HA gives the *next* rising and setting, which after sunrise is
    tomorrow's -- a minute or two off today's, invisible at this scale."""
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    a = state.attributes
    return {
        "rise": local_hours(a.get("next_rising")),
        "set": local_hours(a.get("next_setting")),
        "noon": local_hours(a.get("next_noon")),
        "elevation": _round(a.get("elevation"), 1),
        "azimuth": _round(a.get("azimuth"), 1),
    }


def _round(value: Any, digits: int) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def resample(
    states: list[State], start: datetime, step: timedelta, count: int
) -> list[float | None]:
    """States (oldest first) as `count` evenly spaced values: the reading in
    force at start + step, start + 2*step, ... -- the last point is `now`.
    None where nothing was known yet or the state was not a number."""
    out: list[float | None] = []
    i, current = 0, None
    for k in range(1, count + 1):
        t = start + step * k
        while i < len(states) and states[i].last_changed <= t:
            current = state_number(states[i])
            i += 1
        out.append(None if current is None else round(current, 1))
    return out


class Feeder:
    """Watches the mapped entities and pushes their inputs to the box."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ScopeClient,
        coordinator: ScopeCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.coordinator = coordinator
        self.options: dict[str, Any] = dict(entry.options)
        self.values: dict[str, Any] = {}
        # The screen HA last chose, resent with the inputs after a restart.
        self.last_screen: str | None = None
        self._pending: set[str] = set()
        self._sent_at: dict[str, float] = {}
        self._flush_unsub: Any = None
        self._cutoff = 0.0
        self._unsubs: list[Any] = []
        self._forecast_at: datetime | None = None
        self._stopped = False
        # While starting, changes only collect: the start ends with one push
        # of everything rather than a flurry of partial ones.
        self._holding = True

    # -- lifecycle --------------------------------------------------------
    async def async_start(self) -> None:
        """Read everything once, push it, then follow changes."""
        o = self.options
        watched: dict[str, list[str]] = {}
        for name in (*NUMERIC_INPUTS, *LOCATION_INPUTS):
            if entity := o.get(name):
                watched.setdefault(entity, []).append(name)
        self._watched = watched
        if watched:
            self._unsubs.append(async_track_state_change_event(
                self.hass, list(watched), self._entity_changed))
        if weather := o.get(OPT_WEATHER):
            self._unsubs.append(async_track_state_change_event(
                self.hass, [weather], self._weather_changed))
        self._unsubs.append(async_track_state_change_event(
            self.hass, [SUN], self._sun_changed))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._hourly, HISTORY_INTERVAL))

        # Inputs this integration owns but no longer has a source for are
        # cleared, so a screen shows `--` instead of a stale reading.
        for name in ALL_INPUTS:
            self.values[name] = None
        for entity, names in watched.items():
            self._read(entity, names)
        self.values[IN_SUN] = sun_input(self.hass.states.get(SUN))
        self.values[IN_LOCATION] = {
            "lat": round(self.hass.config.latitude, 3),
            "lon": round(self.hass.config.longitude, 3),
        }
        # A source that fails must not stop the rest from being pushed.
        for step in (self._refresh_forecast(force=True), self._refresh_history()):
            try:
                await step
            except Exception:  # noqa: BLE001
                LOGGER.exception("Could not read a scope input source")
        self._holding = False
        await self.resend_all()

    @callback
    def async_stop(self) -> None:
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._flush_unsub:
            self._flush_unsub()
            self._flush_unsub = None

    # -- sources ----------------------------------------------------------
    @callback
    def _read(self, entity: str, names: list[str]) -> None:
        state = self.hass.states.get(entity)
        for name in names:
            if name in LOCATION_INPUTS:
                self.values[name] = state_location(state)
            else:
                self.values[name] = state_number(state)

    @callback
    def _entity_changed(self, event: Event[EventStateChangedData]) -> None:
        entity = event.data["entity_id"]
        state = event.data["new_state"]
        for name in self._watched.get(entity, ()):
            value = (state_location(state) if name in LOCATION_INPUTS
                     else state_number(state))
            self.set(name, value)

    @callback
    def _weather_changed(self, event: Event[EventStateChangedData]) -> None:
        self.entry.async_create_background_task(
            self.hass, self._refresh_forecast(), f"{DOMAIN} forecast")

    @callback
    def _sun_changed(self, event: Event[EventStateChangedData]) -> None:
        self.set(IN_SUN, sun_input(event.data["new_state"]))

    async def _hourly(self, now: datetime) -> None:
        for step in (self._refresh_forecast(force=True), self._refresh_history()):
            try:
                await step
            except Exception:  # noqa: BLE001
                LOGGER.exception("Could not read a scope input source")

    async def _refresh_forecast(self, force: bool = False) -> None:
        entity = self.options.get(OPT_WEATHER)
        if not entity:
            return
        now = dt_util.utcnow()
        if (not force and self._forecast_at is not None
                and now - self._forecast_at < FORECAST_MIN_INTERVAL):
            return
        self._forecast_at = now
        try:
            resp = await self.hass.services.async_call(
                "weather", "get_forecasts",
                {"entity_id": entity, "type": "hourly"},
                blocking=True, return_response=True,
            )
        except (HomeAssistantError, ValueError) as err:
            LOGGER.debug("No hourly forecast from %s: %s", entity, err)
            return
        forecast = ((resp or {}).get(entity) or {}).get("forecast") or []
        forecast = forecast[:FORECAST_HOURS]
        self.set(IN_FORECAST_TEMP, [_round(f.get("temperature"), 1)
                                    for f in forecast])
        self.set(IN_FORECAST_RAIN, [_round(f.get("precipitation_probability"), 0)
                                    for f in forecast])

    async def _refresh_history(self) -> None:
        if "recorder" not in self.hass.config.components:
            return
        # Imported here: the recorder is optional, and importing it pulls in
        # its database layer.
        from homeassistant.components.recorder import get_instance, history

        for name, option, days, hours in HISTORY_SERIES:
            entity = self.options.get(option)
            if not entity:
                continue
            end = dt_util.utcnow()
            start = end - timedelta(days=days)
            step = timedelta(hours=hours)
            count = days * 24 // hours

            def read(entity=entity, start=start, end=end):
                return history.state_changes_during_period(
                    self.hass, start, end, entity_id=entity,
                    # A weather entity's temperature is an attribute.
                    no_attributes=not entity.startswith("weather."),
                    include_start_time_state=True,
                ).get(entity, [])

            try:
                states = await get_instance(self.hass).async_add_executor_job(read)
            except Exception as err:  # noqa: BLE001 -- the recorder can fail many ways
                LOGGER.warning("Could not read history of %s: %s", entity, err)
                continue
            self.set(name, resample(states, start, step, count))

    # -- pushing ----------------------------------------------------------
    @callback
    def set(self, name: str, value: Any) -> None:
        """Record an input's new value and push it when its window allows."""
        if name in self.values and self.values[name] == value:
            return
        self.values[name] = value
        self._pending.add(name)
        self._schedule()

    @callback
    def _schedule(self, delay: float | None = None) -> None:
        """Arrange the next flush for when the earliest pending input's window
        ends (or after `delay`). The flush is handed that moment as its
        cutoff, so the timer is the gate: a flush never re-reads the clock and
        finds itself a hair early."""
        if self._stopped or self._holding or not self._pending:
            return
        now = time.monotonic()
        if delay is None:
            due = min(self._sent_at.get(n, -math.inf) + THROTTLE_SECONDS
                      for n in self._pending)
            delay = max(0.0, due - now)
        self._cutoff = now + delay
        if self._flush_unsub:
            self._flush_unsub()
        self._flush_unsub = async_call_later(self.hass, delay, self._flush)

    async def _flush(self, _now: Any = None) -> None:
        self._flush_unsub = None
        cutoff = self._cutoff
        ready = {n for n in self._pending
                 if self._sent_at.get(n, -math.inf) + THROTTLE_SECONDS
                 <= cutoff + 0.01}
        if ready:
            self._pending -= ready
            if not await self._push({n: self.values.get(n) for n in ready}):
                self._pending |= ready
                self._schedule(RETRY_SECONDS)
                return
            sent = max(time.monotonic(), cutoff)
            for n in ready:
                self._sent_at[n] = sent
        self._schedule()

    async def _push(self, inputs: dict[str, Any]) -> bool:
        try:
            status = await self.client.put_inputs(inputs)
        except ScopeAuthError as err:
            LOGGER.error("The scope box refused the token: %s", err)
            self.entry.async_start_reauth(self.hass)
            return False
        except ScopeError as err:
            LOGGER.debug("Push to the scope box failed: %s", err)
            self.coordinator.push_failed()
            return False
        self.coordinator.push_result(status)
        return True

    async def resend_all(self) -> None:
        """Push every input (and the screen HA last chose) in one go."""
        if self._stopped or self._holding:
            return
        now = time.monotonic()
        if await self._push(dict(self.values)):
            for n in self.values:
                self._sent_at[n] = now
            self._pending.clear()
        if self.last_screen:
            try:
                self.coordinator.push_result(
                    await self.client.put_screen(screen=self.last_screen))
            except ScopeError as err:
                LOGGER.debug("Could not restore the screen: %s", err)
