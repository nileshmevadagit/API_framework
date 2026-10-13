"""Rate-limit middleware. Runs after auth and before the transport, so every attempt counts.

Emits ``on_rate_limited`` when a call had to wait for quota, or was refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.errors import QuotaExhausted
from apiframework.hooks import RateLimitEvent

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from apiframework.clock import Clock
    from apiframework.hooks import Hooks
    from apiframework.middleware.base import CallNext
    from apiframework.ratelimit import Limiter
    from apiframework.request import RequestSpec


class RateLimitMiddleware:
    def __init__(
        self,
        limiters: Sequence[Limiter],
        *,
        clock: Clock,
        api: str = "",
        hooks: Hooks | None = None,
    ) -> None:
        self._limiters = tuple(limiters)
        self._clock = clock
        self._api = api
        self._hooks = hooks

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        for limiter in self._limiters:
            started = self._clock.monotonic()
            try:
                await limiter.acquire(req.cost)
            except QuotaExhausted:
                self._emit(self._clock.monotonic() - started, exhausted=True)
                raise
            waited = self._clock.monotonic() - started
            if waited > 0:
                self._emit(waited, exhausted=False)
        response = await call_next(req)
        for limiter in self._limiters:
            await limiter.observe(response)
        return response

    def _emit(self, waited: float, *, exhausted: bool) -> None:
        if self._hooks is not None:
            self._hooks.emit_rate_limited(
                RateLimitEvent(api=self._api, waited_s=waited, exhausted=exhausted)
            )
