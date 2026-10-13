"""The Middleware contract: each layer wraps the next one in the chain.

Fixed order (see CLAUDE.md): logging -> retry -> auth -> ratelimit -> transport.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import httpx

    from apiframework.request import RequestSpec

CallNext = Callable[["RequestSpec"], Awaitable["httpx.Response"]]


class Middleware(Protocol):
    """One concern in the request chain. Testable alone, with a fake ``call_next``."""

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        """Handle ``req``, normally by calling ``call_next`` with a (possibly cloned) spec."""
        ...
