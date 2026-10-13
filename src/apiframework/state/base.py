"""StateStore contract: the only thing that outlives a request.

Holds quota counters, OAuth tokens, pagination checkpoints and ETags. It must
never hold response data. Methods are async so SQLite (via a thread) and Redis
fit the same interface.

Expiry: ``expires_at`` is epoch seconds. An expired key reads as absent. For a
window counter, ``expires_at`` is set when the key is created and later ``incr``
calls leave it alone, so one window stays one window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pydantic import JsonValue


class StateStore(Protocol):
    async def get(self, key: str) -> JsonValue | None:
        """Return the value, or None if the key is missing or expired."""
        ...

    async def set(self, key: str, value: JsonValue, *, expires_at: float | None = None) -> None:
        """Replace the value and expiry. Overwrites any existing key."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the key. Deleting a missing key is not an error."""
        ...

    async def incr(self, key: str, amount: int = 1, *, expires_at: float | None = None) -> int:
        """Atomically add ``amount`` and return the new value.

        A missing or expired key starts at 0. Raises TypeError if the key holds
        something other than an integer.
        """
        ...
