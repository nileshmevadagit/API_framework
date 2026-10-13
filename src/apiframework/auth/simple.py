"""Static credentials: API key, bearer token and basic auth. Nothing to refresh."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from apiframework.auth.base import with_header

if TYPE_CHECKING:
    from apiframework.request import RequestSpec


class ApiKeyAuth:
    def __init__(self, name: str, value: str, location: str = "header") -> None:
        self._name = name
        self._value = value
        self._location = location

    async def apply(self, req: RequestSpec) -> RequestSpec:
        if self._location == "query":
            return req.clone(params=(*req.params, (self._name, self._value)))
        return with_header(req, self._name, self._value)

    async def on_unauthorized(self) -> bool:
        return False


class BearerAuth:
    def __init__(self, token: str) -> None:
        self._token = token

    async def apply(self, req: RequestSpec) -> RequestSpec:
        return with_header(req, "Authorization", f"Bearer {self._token}")

    async def on_unauthorized(self) -> bool:
        return False


class BasicAuth:
    def __init__(self, username: str, password: str) -> None:
        self._encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")

    async def apply(self, req: RequestSpec) -> RequestSpec:
        return with_header(req, "Authorization", f"Basic {self._encoded}")

    async def on_unauthorized(self) -> bool:
        return False
