"""The auth handler contract. Handlers add credentials to a request; they never send one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apiframework.request import RequestSpec


class AuthHandler(Protocol):
    async def apply(self, req: RequestSpec) -> RequestSpec:
        """Return ``req`` with credentials added.

        Called on every attempt, so retries get a fresh credential.
        """
        ...

    async def on_unauthorized(self) -> bool:
        """Called after a 401. Return True to retry once with a refreshed credential."""
        ...


def with_header(req: RequestSpec, name: str, value: str) -> RequestSpec:
    """Return a copy with header ``name`` set, replacing any existing header of that name."""
    kept = tuple((key, val) for key, val in req.headers if key.lower() != name.lower())
    return req.clone(headers=(*kept, (name, value)))
