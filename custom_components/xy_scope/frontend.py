"""The dashboard card: the scope's live trace, on a Home Assistant dashboard.

The card draws the box's own planned frame (`GET /api/frame`), the one its
web page previews, so nothing about the figures is re-derived in JavaScript.
The browser never talks to the box: it asks Home Assistant, which fetches
the frame for it. That keeps the card working away from home, behind Home
Assistant's login, while the box stays a LAN-only appliance.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from aiohttp import web

from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.http import (
    KEY_HASS,
    KEY_HASS_USER,
    HomeAssistantView,
    StaticPathConfig,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .api import ScopeError
from .const import DOMAIN

CARD_FILE = "xy-scope-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the card, load it into every dashboard, and open the frame
    route. Once per Home Assistant, not per display."""
    if hass.http is None:
        return
    await hass.http.async_register_static_paths([StaticPathConfig(
        CARD_URL, str(Path(__file__).parent / "card" / CARD_FILE))])
    hass.http.register_view(FrameView())
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        # Versioned, so an update reaches browsers that cached the old card.
        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")


class FrameView(HomeAssistantView):
    """GET /api/xy_scope/frame[?entity_id=select.xy_scope_screen]

    The box's frame, plus the calibrated tube (`max_scale`, `aspect`) so the
    card can frame the trace the way the tube does. `entity_id` picks the
    display by any of its entities; without it there must be just one."""

    url = "/api/xy_scope/frame"
    name = "api:xy_scope:frame"

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        entity_id = request.query.get("entity_id")
        if entity_id and not request[KEY_HASS_USER].permissions.check_entity(
                entity_id, POLICY_READ):
            raise Unauthorized(entity_id=entity_id)
        entry = _entry_for(hass, entity_id)
        if entry is None:
            return self.json_message(
                "No XY Scope display found", HTTPStatus.NOT_FOUND)
        try:
            frame = await entry.runtime_data.client.frame()
        except ScopeError as err:
            return self.json_message(str(err), HTTPStatus.BAD_GATEWAY)
        status = entry.runtime_data.coordinator.data or {}
        frame["max_scale"] = status.get("max_scale", 1.0)
        frame["aspect"] = status.get("aspect", 1.0)
        return self.json(frame)


def _entry_for(hass: HomeAssistant, entity_id: str | None) -> ConfigEntry | None:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if e.state is ConfigEntryState.LOADED]
    if entity_id is None:
        return entries[0] if len(entries) == 1 else None
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None:
        return None
    return next((e for e in entries if e.entry_id == entity.config_entry_id), None)
