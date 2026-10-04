"""XY Scope Display: Home Assistant feeds an oscilloscope vector display.

The box (xy-bench) draws screens -- a clock with temperatures, weather as
curves and bars, plant moisture, a street map -- from named inputs. This
integration maps entities onto those inputs, keeps them fresh, and exposes the
display as entities: the screen (select), the scale (number), display power
(switch, wrapping the scope's outlet) and a few status sensors. Automations
then only decide which screen shows and when the display is on.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.start import async_at_started

from .api import ScopeClient
from .const import DOMAIN
from .coordinator import ScopeCoordinator
from .feeder import Feeder

PLATFORMS = [Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]


@dataclass
class ScopeData:
    client: ScopeClient
    coordinator: ScopeCoordinator
    feeder: Feeder


type ScopeConfigEntry = ConfigEntry[ScopeData]


async def async_setup_entry(hass: HomeAssistant, entry: ScopeConfigEntry) -> bool:
    client = ScopeClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
    )
    coordinator = ScopeCoordinator(hass, entry, client)
    # Not ready (and retried by HA) until the box answers.
    await coordinator.async_config_entry_first_refresh()

    feeder = Feeder(hass, entry, client, coordinator)
    coordinator.on_reconnect = feeder.resend_all
    entry.runtime_data = ScopeData(client, coordinator, feeder)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(feeder.async_stop)
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    # Start feeding once Home Assistant is fully up: during its start the
    # sources (the weather entity, sensors still restoring) may not exist
    # yet, and pushing them then would only blank the screens with `--`.
    # Reading history can take a while, so it runs in the background.
    @callback
    def _start(_hass: HomeAssistant) -> None:
        entry.async_create_background_task(
            hass, feeder.async_start(), f"{DOMAIN} feeder start")

    entry.async_on_unload(async_at_started(hass, _start))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ScopeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_changed(hass: HomeAssistant, entry: ScopeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
