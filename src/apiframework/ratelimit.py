"""Rate limits: throughput and quotas.

Per-second limits are a token bucket held in memory (throughput). Hour and day limits are
fixed windows aligned to the epoch, counted in a StateStore (quota), so they survive a
restart and can be shared by workers that use the same store.

Server ``RateLimit-*`` / ``X-RateLimit-*`` headers correct the local window counter.
Per-second buckets ignore them: the server's own limit cannot be applied to a bucket
without knowing how it refills.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

from apiframework.errors import ConfigError, QuotaExhausted

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from apiframework.clock import Clock
    from apiframework.config import RateLimitConfig
    from apiframework.state import StateStore

WINDOW_SECONDS = {"hour": 3600, "day": 86400}
REMAINING_HEADERS = ("RateLimit-Remaining", "X-RateLimit-Remaining")
RESET_HEADERS = ("RateLimit-Reset", "X-RateLimit-Reset")
EPOCH_THRESHOLD = 1_000_000_000  # reset values above this are epoch times, below are seconds


class Limiter(Protocol):
    async def acquire(self, cost: int) -> None:
        """Wait or raise until ``cost`` units are available, then take them."""
        ...

    async def observe(self, response: httpx.Response) -> None:
        """Learn from a response, such as the server's remaining count."""
        ...


class TokenBucket:
    """Throughput limit: ``rate`` units per second, with bursts up to ``capacity``."""

    def __init__(self, *, rate: float, capacity: float, clock: Clock) -> None:
        self._rate = rate
        self._capacity = capacity
        self._clock = clock
        self._tokens = capacity
        self._updated = clock.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: int) -> None:
        if cost > self._capacity:
            raise ConfigError(f"request cost {cost} exceeds the per-second limit")
        async with self._lock:
            while True:
                now = self._clock.monotonic()
                elapsed = now - self._updated
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._updated = now
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                await self._clock.sleep((cost - self._tokens) / self._rate)

    async def observe(self, response: httpx.Response) -> None:
        return None


class FixedWindow:
    """Quota limit per epoch-aligned hour or day, counted in the state store."""

    def __init__(
        self,
        *,
        api: str,
        window: str,
        limit: int,
        on_exhausted: str,
        state: StateStore,
        clock: Clock,
    ) -> None:
        self._name = f"{api}:{window}"
        self._seconds = WINDOW_SECONDS[window]
        self._limit = limit
        self._on_exhausted = on_exhausted
        self._state = state
        self._clock = clock
        # The server's own window, while it is active. Its count replaces the local one.
        self._server_reset = 0.0
        self._server_used = 0

    def _current(self) -> tuple[str, float]:
        """Return the counter key for the current window and the time it resets."""
        start = math.floor(self._clock.now() / self._seconds) * self._seconds
        return f"ratelimit:{self._name}:{int(start)}", start + self._seconds

    def _server_active(self) -> bool:
        return self._clock.now() < self._server_reset

    async def acquire(self, cost: int) -> None:
        if cost > self._limit:
            raise ConfigError(f"request cost {cost} exceeds the {self._name} quota")
        while True:
            if self._server_active() and self._server_used + cost > self._limit:
                await self._exhausted(self._server_reset)
                continue
            key, reset = self._current()
            used = await self._state.incr(key, cost, expires_at=reset)
            if used > self._limit:
                await self._state.incr(key, -cost)  # a refused request does not use quota
                await self._exhausted(reset)
                continue
            if self._server_active():
                self._server_used += cost
            return

    async def _exhausted(self, reset_at: float) -> None:
        if self._on_exhausted == "raise":
            when = datetime.fromtimestamp(reset_at, tz=timezone.utc)
            raise QuotaExhausted(self._name, when)
        await self._clock.sleep(max(0.0, reset_at - self._clock.now()))

    async def observe(self, response: httpx.Response) -> None:
        remaining = _int_header(response, REMAINING_HEADERS)
        if remaining is None:
            return
        used = self._limit - max(0, remaining)
        reset_at = _reset_time(response, self._clock.now())
        if reset_at is not None and reset_at > self._clock.now():
            # The server's window is known: it governs until it resets.
            self._server_reset = reset_at
            self._server_used = used
            return
        key, reset = self._current()
        await self._state.set(key, used, expires_at=reset)


class RateLimiters:
    """Limiters looked up by key (the API name). Share one instance to share a quota."""

    def __init__(self, *, state: StateStore, clock: Clock) -> None:
        self._state = state
        self._clock = clock
        self._by_key: dict[str, tuple[Limiter, ...]] = {}

    def for_key(self, key: str, configs: Sequence[RateLimitConfig]) -> tuple[Limiter, ...]:
        if key not in self._by_key:
            self._by_key[key] = tuple(self._build(key, config) for config in configs)
        return self._by_key[key]

    def _build(self, key: str, config: RateLimitConfig) -> Limiter:
        if config.window == "second":
            return TokenBucket(rate=config.limit, capacity=config.limit, clock=self._clock)
        return FixedWindow(
            api=key,
            window=config.window,
            limit=config.limit,
            on_exhausted=config.on_exhausted,
            state=self._state,
            clock=self._clock,
        )


def _int_header(response: httpx.Response, names: tuple[str, ...]) -> int | None:
    for name in names:
        raw = response.headers.get(name)
        if raw is not None:
            try:
                return int(raw.strip())
            except ValueError:
                return None
    return None


def _reset_time(response: httpx.Response, now: float) -> float | None:
    value = _int_header(response, RESET_HEADERS)
    if value is None:
        return None
    return float(value) if value > EPOCH_THRESHOLD else now + value
