"""Layla's REST API (read-only use: the user, the properties, and each property's devices with their latest
readings)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import aiohttp

from .auth import LaylaAuthError, LaylaConnectError, Tokens, refresh
from .settings import Endpoints

# The optional sections Layla's own web app asks for with a property's devices
DEVICE_FIELDS = "latest_values,alarm_event_counts,in_alarm,active_alarms,mode"


class LaylaApiError(Exception):
    """The API answered with an error, or couldn't be reached."""


def _unwrap(body: Any, *keys: str) -> list[Any]:
    """A list, or a list wrapped in an object under one of keys."""
    if isinstance(body, dict):
        for key in keys:
            if isinstance(body.get(key), list):
                return body[key]
        return []
    return body if isinstance(body, list) else []


class LaylaApi:
    """Calls the API with a fresh access token; a refused token is renewed once, then reported."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        run_blocking: Callable[..., Awaitable[Any]],
        on_refresh_token: Callable[[str], None],
        tokens: Tokens | None = None,
        endpoints: Endpoints | None = None,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._run = run_blocking
        self._on_refresh_token = on_refresh_token
        self._tokens = tokens
        self._endpoints = endpoints or Endpoints()
        self._lock = asyncio.Lock()

    async def _access_token(self, force: bool = False) -> str:
        async with self._lock:
            t = self._tokens
            if force or t is None or t.expires_at - time.time() < 300:
                t = await self._run(refresh, self._refresh_token, self._endpoints)
                self._tokens = t
                if t.refresh_token and t.refresh_token != self._refresh_token:
                    self._refresh_token = t.refresh_token
                    self._on_refresh_token(t.refresh_token)
            return t.access_token

    async def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        for attempt in (0, 1):
            token = await self._access_token(force=attempt == 1)
            try:
                async with self._session.get(
                    self._endpoints.api_url + path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        continue
                    if resp.status == 401:
                        raise LaylaAuthError("Layla refused the session: sign in again")
                    if resp.status == 429:
                        raise LaylaApiError("Layla asked to slow down (429)")
                    if resp.status >= 400:
                        raise LaylaApiError(f"Layla answered {resp.status} for {path}")
                    return await resp.json(content_type=None)
            except (TimeoutError, aiohttp.ClientError, ValueError) as err:
                raise LaylaApiError(f"couldn't reach Layla: {err}") from err
        raise LaylaApiError("unreachable")

    async def user(self) -> Any:
        return await self.get("/v1/users/self")

    async def properties(self) -> list[dict[str, Any]]:
        """The account's properties (each with an id, a name and a time zone)."""
        return [p for p in _unwrap(await self.get("/v1/properties"), "data", "properties") if isinstance(p, dict) and p.get("id")]

    async def devices(self, properties: Iterable[dict[str, Any]]) -> tuple[list[Any], dict[str, str]]:
        """Each property's devices with their readings, alarms and status. Those are optional sections that only
        the per-property list sends, when asked for (as Layla's own web app does): the all-devices list leaves
        them out, so a device would look offline and empty.

        A property that fails to answer is skipped (its devices show as unavailable), and returned with the error,
        as (devices, {property id: error}). Only when every property fails does this raise."""
        out: list[Any] = []
        failed: dict[str, str] = {}
        last: LaylaApiError | None = None
        properties = list(properties)
        for p in properties:
            pid = str(p["id"])
            try:
                body = await self.get("/v1/devices", {"property_id": pid, "fields": DEVICE_FIELDS})
            except LaylaApiError as err:  # (a refused session isn't one: that ends the update)
                failed[pid] = str(err)
                last = err
                continue
            for d in _unwrap(body, "data", "devices"):
                if isinstance(d, dict):
                    # its readings' times are the property's wall clock, without a zone
                    out.append({**d, "_timezone": p.get("timezone") or "", "_property_name": p.get("name") or ""})
        if last is not None and len(failed) == len(properties):
            raise last
        return out, failed


__all__ = ["LaylaApi", "LaylaApiError", "LaylaAuthError", "LaylaConnectError"]
