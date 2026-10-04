"""A small client for the scope box's push API.

The box (xy-bench) draws; Home Assistant feeds it. Three calls:

    GET /api/status    version, boot id, screen, screens, scale, fps, inputs
    PUT /api/inputs    merge named inputs; null removes one
    PUT /api/screen    {"screen": name, "scale": 0..1}, either optional

Writes carry the shared token as a bearer token.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import API_VERSION

TIMEOUT = aiohttp.ClientTimeout(total=10)


class ScopeError(Exception):
    """Base class for talking to the box."""


class ScopeConnectionError(ScopeError):
    """The box did not answer."""


class ScopeAuthError(ScopeError):
    """The box refused the token (or has none set)."""


class ScopeApiError(ScopeError):
    """The box answered, but not with what was expected."""


class ScopeVersionError(ScopeApiError):
    """The box speaks a different push API version."""


class ScopeClient:
    """Talks to one box."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, port: int, token: str
    ) -> None:
        self._session = session
        self._token = token
        self.base = f"http://{host}:{port}"

    async def status(self) -> dict[str, Any]:
        """The box's status, checked for an API version this client speaks."""
        status = await self._request("GET", "/api/status")
        if status.get("api") != API_VERSION:
            raise ScopeVersionError(
                f"box speaks push API {status.get('api')!r}, "
                f"this integration speaks {API_VERSION}"
            )
        return status

    async def put_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Merge inputs on the box (None removes one); returns the status."""
        return await self._request("PUT", "/api/inputs", inputs)

    async def put_screen(
        self, screen: str | None = None, scale: float | None = None
    ) -> dict[str, Any]:
        """Change the screen and/or scale; returns the status."""
        body: dict[str, Any] = {}
        if screen is not None:
            body["screen"] = screen
        if scale is not None:
            body["scale"] = scale
        return await self._request("PUT", "/api/screen", body)

    async def check_token(self) -> None:
        """Prove the token works without changing anything: an empty merge."""
        await self.put_inputs({})

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {}
        if method != "GET":
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method, self.base + path, json=body, headers=headers,
                timeout=TIMEOUT,
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except ValueError:
                    data = None
                if resp.status in (401, 403):
                    raise ScopeAuthError(_error(data, resp.status))
                if resp.status >= 400:
                    raise ScopeApiError(_error(data, resp.status))
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ScopeConnectionError(
                f"{method} {self.base}{path} failed: {err!r}"
            ) from err
        if not isinstance(data, dict):
            raise ScopeApiError(f"{method} {path}: expected a JSON object")
        return data


def _error(data: Any, status: int) -> str:
    if isinstance(data, dict) and data.get("error"):
        return f"HTTP {status}: {data['error']}"
    return f"HTTP {status}"
