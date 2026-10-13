"""Rate-limit middleware. Runs after auth and before the transport, so every attempt counts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from apiframework.middleware.base import CallNext
    from apiframework.ratelimit import Limiter
    from apiframework.request import RequestSpec


class RateLimitMiddleware:
    def __init__(self, limiters: Sequence[Limiter]) -> None:
        self._limiters = tuple(limiters)

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        for limiter in self._limiters:
            await limiter.acquire(req.cost)
        response = await call_next(req)
        for limiter in self._limiters:
            await limiter.observe(response)
        return response
