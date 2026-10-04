"""Shared fixtures: a fake scope box standing in for the HTTP client."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from custom_components.xy_scope.api import ScopeAuthError, ScopeConnectionError
from custom_components.xy_scope.const import API_VERSION

SCREENS = ["home", "clock", "weather", "welcome"]


class FakeBox:
    """Behaves like the box's push API, and records what it was sent."""

    def __init__(self) -> None:
        self.boot = "boot-1"
        self.screen = "clock"
        self.scale = 0.6
        self.inputs: dict[str, Any] = {}
        self.pushes: list[dict[str, Any]] = []
        self.screens_set: list[str] = []
        self.down = False
        self.token_ok = True
        self.api = API_VERSION

    def status_dict(self) -> dict[str, Any]:
        return {
            "api": self.api, "boot": self.boot, "uptime": 1,
            "screen": self.screen,
            "screens": [{"name": n, "label": n.title()} for n in SCREENS],
            "scale": self.scale, "max_scale": 0.63, "playing": True,
            "error": None, "fps": 50.0,
            "inputs": {k: 0.0 for k in self.inputs},
        }

    def _check(self, write: bool) -> None:
        if self.down:
            raise ScopeConnectionError("down")
        if write and not self.token_ok:
            raise ScopeAuthError("HTTP 401")

    # The client's interface.
    async def status(self) -> dict[str, Any]:
        self._check(False)
        if self.api != API_VERSION:
            from custom_components.xy_scope.api import ScopeVersionError
            raise ScopeVersionError("version")
        return self.status_dict()

    async def put_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self._check(True)
        self.pushes.append(dict(inputs))
        for k, v in inputs.items():
            if v is None:
                self.inputs.pop(k, None)
            else:
                self.inputs[k] = v
        return self.status_dict()

    async def put_screen(self, screen=None, scale=None) -> dict[str, Any]:
        self._check(True)
        if screen is not None:
            self.screen = screen
            self.screens_set.append(screen)
        if scale is not None:
            self.scale = min(scale, 0.63)
        return self.status_dict()

    async def check_token(self) -> None:
        await self.put_inputs({})

    base = "http://box:8080"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def box():
    fake = FakeBox()
    factory = lambda *a, **k: fake  # noqa: E731
    with patch("custom_components.xy_scope.ScopeClient", factory), \
         patch("custom_components.xy_scope.config_flow.ScopeClient", factory):
        yield fake
