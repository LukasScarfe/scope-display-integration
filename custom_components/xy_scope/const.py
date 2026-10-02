"""Constants for the XY Scope Display integration."""

from datetime import timedelta
import logging

DOMAIN = "xy_scope"
LOGGER = logging.getLogger(__package__)

# The box's push API version this integration speaks (GET /api/status "api").
API_VERSION = 1

DEFAULT_PORT = 8080

# How often the box's status is polled. Also how soon a restarted or
# returning box gets every input resent.
STATUS_INTERVAL = timedelta(seconds=60)

# An input is pushed at most this often; changes in between are coalesced
# and the latest value goes out when the window ends.
THROTTLE_SECONDS = 10.0

# History series are re-read this often (they only grow by one point an hour).
HISTORY_INTERVAL = timedelta(hours=1)

# The hourly forecast is fetched when the weather entity updates, but no more
# often than this.
FORECAST_MIN_INTERVAL = timedelta(minutes=5)

# Options: which entity feeds each screen input, plus the display's outlet.
OPT_INSIDE_TEMP = "inside_temp"
OPT_OUTSIDE_TEMP = "outside_temp"
OPT_HIGH_TEMP = "high_temp"
OPT_LOW_TEMP = "low_temp"
OPT_WEATHER = "weather"
OPT_PLANT_A = "plant_a"
OPT_PLANT_B = "plant_b"
OPT_CAR_A = "car_a"
OPT_CAR_B = "car_b"
OPT_POWER = "power_switch"

ENTITY_OPTIONS = (
    OPT_INSIDE_TEMP, OPT_OUTSIDE_TEMP, OPT_HIGH_TEMP, OPT_LOW_TEMP,
    OPT_WEATHER, OPT_PLANT_A, OPT_PLANT_B, OPT_CAR_A, OPT_CAR_B, OPT_POWER,
)

# Inputs that are a single number, pushed straight from an entity's state.
NUMERIC_INPUTS = (OPT_INSIDE_TEMP, OPT_OUTSIDE_TEMP, OPT_HIGH_TEMP, OPT_LOW_TEMP)

# Location inputs: {"lat": .., "lon": ..} from an entity's attributes.
LOCATION_INPUTS = (OPT_CAR_A, OPT_CAR_B)

# Box input names for the derived series.
IN_FORECAST_TEMP = "forecast_temp"   # next 24 h, hourly
IN_FORECAST_RAIN = "forecast_rain"   # next 24 h, hourly, % chance
IN_INSIDE_WEEK = "inside_week"       # last 7 d, hourly
IN_OUTSIDE_WEEK = "outside_week"     # last 7 d, hourly
IN_SUN = "sun"                       # rise/set/noon (local hours), elevation
IN_LOCATION = "location"             # home lat/lon, for sky maths on the box
IN_WEATHER_NOW = "weather_now"       # the weather entity's current readings

# Current readings copied from the weather entity into `weather_now`.
WEATHER_NOW_ATTRS = ("humidity", "wind_speed", "wind_bearing", "pressure",
                     "cloud_coverage", "uv_index", "dew_point")

FORECAST_HOURS = 24

# (box input, option naming the entity, days, hours per point)
HISTORY_SERIES = (
    (OPT_PLANT_A, OPT_PLANT_A, 14, 2),
    (OPT_PLANT_B, OPT_PLANT_B, 14, 2),
    (IN_INSIDE_WEEK, OPT_INSIDE_TEMP, 7, 1),
    (IN_OUTSIDE_WEEK, OPT_OUTSIDE_TEMP, 7, 1),
)

# Every input this integration owns on the box: ones no longer mapped are
# cleared there, so a screen shows `--` rather than a stale reading.
ALL_INPUTS = (
    *NUMERIC_INPUTS, *LOCATION_INPUTS, IN_FORECAST_TEMP, IN_FORECAST_RAIN,
    *(name for name, *_ in HISTORY_SERIES), IN_SUN, IN_LOCATION,
    IN_WEATHER_NOW,
)
