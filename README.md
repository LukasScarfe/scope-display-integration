# XY Scope Display

A Home Assistant integration for an oscilloscope used as a vector display: a
stereo DAC drives the scope in X-Y mode, and the box behind it
([xy-bench](#the-box)) draws glanceable screens (a clock with temperatures,
weather as curves and bars, plant moisture, a street map around the parked
car) as single-stroke line art.

The box draws; Home Assistant decides. This integration:

- **feeds the screens.** You map an entity to each screen input once (inside
  and outside temperature, today's high and low, the hourly forecast, two soil
  moisture sensors, two car locations). It pushes each one when it changes, at
  most every 10 seconds, reads recorder history for the history screens, and
  refills a box that restarted or was unreachable.
- **exposes the display** as one device: the current **screen** (select),
  the **scale** (number), **display power** (switch, wrapping the scope's
  smart outlet), and status sensors.

Automations then only decide which screen shows and when the display is on.

## Install

Through [HACS](https://hacs.xyz): *HACS → ⋮ → Custom repositories*, add
`https://github.com/LukasScarfe/scope-display-integration` as an
**Integration**, install **XY Scope Display**, and restart Home Assistant.

Manually: copy `custom_components/xy_scope` into your config's
`custom_components/` and restart.

Requires Home Assistant 2026.9 or newer.

## Set up

*Settings → Devices & services → Add integration → XY Scope Display*, then:

- **Host** and **port** of the box (its web page; 8080 by default).
- **Token**: the box's `XYBENCH_TOKEN`, from its `.env`.

The integration checks the box answers and accepts the token before saving.

Then *Configure* to see the screen inputs. They come pre-filled with guesses
found by device class and name (temperature sensors, a weather entity with an
hourly forecast, moisture sensors, anything with "car" or "park" and a
location, a switch with "scope" in its name). Change or clear any of them; a
cleared input shows as `--` on the display.

| Option | Feeds | Pushed as |
|---|---|---|
| Inside temperature | Home; Temp week | `inside_temp`, `inside_week` (7 days, hourly) |
| Outside temperature | Home, Weather; Temp week | `outside_temp`, `outside_week` |
| Today's high / low | Weather | `high_temp`, `low_temp` |
| Forecast (hourly) | Weather | `forecast_temp`, `forecast_rain` (next 24 h) |
| Plant 1 / 2 soil moisture | Plants (solid / dotted line) | `plant_a`, `plant_b` (14 days, every 2 h) |
| Car 1 / 2 location | Car map | `car_a`, `car_b` (`{"lat", "lon"}`) |
| Display outlet | Display power switch | (not pushed) |

Also pushed: `sun` (today's rise, noon and set as local hours, and the sun's
elevation and azimuth now, from `sun.sun`), `location` (home's latitude and
longitude, for the sky maths on the box) and, with a forecast entity set,
`weather_now` (its condition -- `sunny`, `rainy`, ... -- and its humidity,
wind speed and bearing, pressure, cloud cover, UV index and dew point).

An entity that is unavailable or unknown is treated as no news: the box keeps
the last good value instead of blanking to `--` whenever Home Assistant
restarts or a sensor misses a report. Clearing an option clears its input.

## Entities

| Entity | What it does |
|---|---|
| `select.xy_scope_screen` | The screen shown. Options are the box's own screen names (`home`, `weather`, `welcome`, ...). |
| `number.xy_scope_scale` | Picture size, 0.05 up to the maximum calibrated on the box. |
| `switch.xy_scope_display_power` | The scope's outlet. Off really cuts power: a stopped signal would park the beam on one spot and burn the phosphor. Only created when an outlet is set in the options. |
| `sensor.xy_scope_current_screen` | The screen shown, as text. |
| `sensor.xy_scope_output` | `playing`, `stopped` or `error` (the audio feed into the scope). |
| `sensor.xy_scope_frame_rate` | Frames per second; long screens draw slower, down to the box's floor (50). |
| `sensor.xy_scope_inputs` | How many inputs the box holds; the `ages` attribute shows each one's age in seconds. |

## Automations

Show the welcome screen when someone arrives, then go back home:

```yaml
triggers:
  - trigger: zone
    entity_id: person.someone
    zone: zone.home
    event: enter
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.xy_scope_display_power
  - action: select.select_option
    target:
      entity_id: select.xy_scope_screen
    data:
      option: welcome
  - delay: 20
  - action: select.select_option
    target:
      entity_id: select.xy_scope_screen
    data:
      option: home
```

Display power off when nobody is home:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: zone.home
    below: 1
    for:
      minutes: 1
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.xy_scope_display_power
```

## The box

The box is a small stdlib-only Python server that turns screens into a stereo
audio stream. Its push API, which this integration speaks (version 1):

```
GET /api/status    {"api": 1, "boot": "<id per process>", "screen": "home",
                    "screens": [{"name", "label"}], "scale", "max_scale",
                    "playing", "error", "fps", "inputs": {name: age_seconds}}
PUT /api/inputs    {"inside_temp": 21.5, "old_input": null}
                   merge; null removes; any name [a-z][a-z0-9_]{0,47}
PUT /api/screen    {"screen": "home", "scale": 0.6}    either key optional
```

Writes carry `Authorization: Bearer <XYBENCH_TOKEN>`. Series are evenly
spaced lists of numbers, oldest first, ending now, with `null` for gaps.

## Development

```
uv venv -p 3.14 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```
