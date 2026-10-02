"""Polls the box's status, and notices when it needs refilling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ScopeClient, ScopeError
from .const import DOMAIN, LOGGER, STATUS_INTERVAL


class ScopeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """The box's last status. Entities read it; pushes refresh it early.

    A box that restarted (its `boot` id changed) or came back after being
    unreachable may have missed pushes, so `on_reconnect` is called to resend
    everything. The box persists its inputs, so this is belt and braces for a
    restart, and the real fix for an outage.
    """

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: ScopeClient
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=STATUS_INTERVAL,
        )
        self.client = client
        self.on_reconnect: Callable[[], Awaitable[None]] | None = None
        self._boot: str | None = None
        self._lost = False

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.client.status()
        except ScopeError as err:
            self._lost = True
            raise UpdateFailed(str(err)) from err
        self.observe(status)
        return status

    @callback
    def observe(self, status: dict[str, Any]) -> None:
        """Track the box's boot id from any status it returns (polls and push
        replies alike) and schedule a resend when it restarted or returned."""
        boot = status.get("boot")
        restarted = self._boot is not None and boot != self._boot
        lost = self._lost
        # Recorded before the resend starts: HA starts tasks eagerly, so the
        # resend's own reply comes back through here before this returns, and
        # must not look like yet another restart.
        self._boot = boot
        self._lost = False
        if (restarted or lost) and self.on_reconnect is not None:
            LOGGER.info(
                "Scope box %s; resending every input",
                "restarted" if restarted else "is back",
            )
            self.config_entry.async_create_background_task(
                self.hass, self.on_reconnect(), f"{DOMAIN} resend"
            )

    @callback
    def push_result(self, status: dict[str, Any]) -> None:
        """A push came back with fresh status: use it, no need to wait."""
        self.observe(status)
        self.async_set_updated_data(status)

    @callback
    def push_failed(self) -> None:
        """A push could not reach the box: treat it as lost until it answers."""
        self._lost = True
