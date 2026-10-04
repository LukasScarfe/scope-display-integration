"""The dashboard card's side of the integration: the card file is served,
and the frame route hands the box's frame to a logged-in browser."""

from http import HTTPStatus

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xy_scope.const import DOMAIN
from custom_components.xy_scope.frontend import CARD_URL

DATA = {CONF_HOST: "192.0.2.10", CONF_PORT: 8080, CONF_TOKEN: "secret"}
FRAME = "/api/xy_scope/frame"


@pytest.fixture
async def entry(hass: HomeAssistant, box):
    e = MockConfigEntry(domain=DOMAIN, data=DATA, options={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return e


async def test_card_file_is_served(hass, entry, hass_client):
    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == HTTPStatus.OK
    assert "customElements.define(\"xy-scope-card\"" in await resp.text()


async def test_frame_carries_the_calibrated_tube(hass, entry, hass_client):
    client = await hass_client()
    for query in ("", "?entity_id=select.xy_scope_screen"):
        resp = await client.get(FRAME + query)
        assert resp.status == HTTPStatus.OK
        frame = await resp.json()
        assert frame["pts"] == [0.0, 0.0, 0.5, 0.5]
        assert (frame["max_scale"], frame["aspect"]) == (0.63, 1.25)


async def test_frame_needs_a_login(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    assert (await client.get(FRAME)).status == HTTPStatus.UNAUTHORIZED


async def test_unknown_display_is_not_found(hass, entry, hass_client):
    client = await hass_client()
    resp = await client.get(FRAME + "?entity_id=select.nope")
    assert resp.status == HTTPStatus.NOT_FOUND


async def test_box_down_is_a_bad_gateway(hass, entry, hass_client, box):
    box.down = True
    client = await hass_client()
    assert (await client.get(FRAME)).status == HTTPStatus.BAD_GATEWAY
