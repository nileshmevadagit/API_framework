"""OAuth2 client credentials, with a cached token that is refreshed before it expires.

Concurrent requests that find the token missing share one refresh: a lock covers the
fetch and the cache is checked again inside it. Tokens live in the StateStore, so a
durable store also keeps them across restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import httpx

from apiframework.auth.base import with_header
from apiframework.errors import AuthError

if TYPE_CHECKING:
    from apiframework.clock import Clock
    from apiframework.request import RequestSpec
    from apiframework.state import StateStore

DEFAULT_EXPIRES_IN = 3600.0


class OAuth2Auth:
    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        clock: Clock,
        state: StateStore,
        scope: str | None = None,
        refresh_margin: float = 60.0,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._margin = refresh_margin
        self._timeout = timeout
        self._transport = transport
        self._clock = clock
        self._state = state
        self._lock = asyncio.Lock()
        digest = hashlib.sha256(f"{token_url}\n{client_id}".encode()).hexdigest()
        self._key = f"oauth2:{digest}"

    async def apply(self, req: RequestSpec) -> RequestSpec:
        token = await self._access_token()
        return with_header(req, "Authorization", f"Bearer {token}")

    async def on_unauthorized(self) -> bool:
        # The server rejected the token, so drop it and let the next attempt fetch one.
        await self._state.delete(self._key)
        return True

    async def _access_token(self) -> str:
        cached = await self._cached()
        if cached is not None:
            return cached
        async with self._lock:
            cached = await self._cached()  # another task may have refreshed while we waited
            if cached is not None:
                return cached
            return await self._fetch()

    async def _cached(self) -> str | None:
        value = await self._state.get(self._key)
        if not isinstance(value, dict):
            return None
        token = value.get("access_token")
        expires_at = value.get("expires_at")
        if not isinstance(token, str) or not isinstance(expires_at, (int, float)):
            return None
        if expires_at - self._margin > self._clock.now():
            return token
        return None

    async def _fetch(self) -> str:
        form = {"grant_type": "client_credentials"}
        if self._scope:
            form["scope"] = self._scope
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
            try:
                response = await http.post(
                    self._token_url,
                    data=form,
                    auth=(self._client_id, self._client_secret),
                )
            except httpx.HTTPError as exc:
                # Name the error type only: its message can echo request details.
                raise AuthError(f"token request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise AuthError(f"token endpoint returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError("token endpoint did not return JSON") from exc
        if not isinstance(body, dict):
            raise AuthError("token response is not a JSON object")
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError("token response has no access_token")
        expires_in = body.get("expires_in", DEFAULT_EXPIRES_IN)
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise AuthError("token response has an invalid expires_in")
        expires_at = self._clock.now() + float(expires_in)
        await self._state.set(
            self._key,
            {"access_token": token, "expires_at": expires_at},
            expires_at=expires_at,
        )
        return token
