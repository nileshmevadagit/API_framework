"""Rate limits: token bucket, epoch-aligned quota windows, server headers, shared registry."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.client import AsyncClient
from apiframework.config import RateLimitConfig, parse_config
from apiframework.errors import ConfigError, QuotaExhausted
from apiframework.ratelimit import FixedWindow, RateLimiters, TokenBucket
from apiframework.state import MemoryStateStore

if TYPE_CHECKING:
    from fakes import FakeClock

BASE = "https://api.test/v1"


async def test_token_bucket_allows_burst_then_waits(clock: FakeClock) -> None:
    bucket = TokenBucket(rate=1.0, capacity=2.0, clock=clock)
    await bucket.acquire(1)
    await bucket.acquire(1)
    assert clock.slept == []
    await bucket.acquire(1)
    assert clock.slept == [pytest.approx(1.0)]


async def test_token_bucket_refills_while_idle(clock: FakeClock) -> None:
    bucket = TokenBucket(rate=2.0, capacity=2.0, clock=clock)
    await bucket.acquire(2)
    clock.advance(1.0)  # refills two tokens
    await bucket.acquire(2)
    assert clock.slept == []


async def test_token_bucket_cost_above_capacity_is_a_config_error(clock: FakeClock) -> None:
    with pytest.raises(ConfigError, match="exceeds"):
        await TokenBucket(rate=1.0, capacity=2.0, clock=clock).acquire(3)


def _window(clock: FakeClock, state: MemoryStateStore, on_exhausted: str = "raise") -> FixedWindow:
    return FixedWindow(
        api="demo",
        window="hour",
        limit=2,
        on_exhausted=on_exhausted,
        state=state,
        clock=clock,
    )


def _next_hour_end(now: float) -> float:
    return (int(now // 3600) + 1) * 3600.0


async def test_quota_raises_with_reset_time(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock))
    await window.acquire(1)
    await window.acquire(1)
    with pytest.raises(QuotaExhausted) as info:
        await window.acquire(1)
    expected = dt.datetime.fromtimestamp(_next_hour_end(clock.now()), tz=dt.timezone.utc)
    assert info.value.reset_at == expected


async def test_refused_request_does_not_use_quota(clock: FakeClock) -> None:
    state = MemoryStateStore(clock)
    window = _window(clock, state)
    await window.acquire(1)
    await window.acquire(1)
    for _ in range(3):
        with pytest.raises(QuotaExhausted):
            await window.acquire(1)
    # Counter key format is internal; the check is that refused calls did not add to it.
    key = f"ratelimit:demo:hour:{int(clock.now() // 3600) * 3600}"
    assert await state.get(key) == 2


async def test_quota_sleeps_until_reset_when_configured(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock), on_exhausted="sleep")
    await window.acquire(1)
    await window.acquire(1)
    before = clock.now()
    await window.acquire(1)
    assert clock.now() == pytest.approx(_next_hour_end(before))


async def test_quota_resets_in_the_next_window(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock))
    await window.acquire(1)
    await window.acquire(1)
    clock.advance(3600.0)
    await window.acquire(1)  # new window, counter starts again


async def test_cost_above_quota_is_a_config_error(clock: FakeClock) -> None:
    with pytest.raises(ConfigError):
        await _window(clock, MemoryStateStore(clock)).acquire(5)


def _response(**headers: str) -> httpx.Response:
    return httpx.Response(200, headers=headers)


async def test_server_zero_remaining_blocks_until_its_reset(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock))
    await window.observe(_response(**{"RateLimit-Remaining": "0", "RateLimit-Reset": "120"}))
    with pytest.raises(QuotaExhausted) as info:
        await window.acquire(1)  # local counter has room, the server says no
    assert info.value.reset_at.timestamp() == pytest.approx(clock.now() + 120)


async def test_x_prefixed_epoch_reset_header_is_read_as_epoch(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock))
    reset_epoch = int(clock.now()) + 45
    await window.observe(
        _response(**{"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_epoch)})
    )
    with pytest.raises(QuotaExhausted) as info:
        await window.acquire(1)
    assert info.value.reset_at.timestamp() == reset_epoch


async def test_server_remaining_overrides_local_counter(clock: FakeClock) -> None:
    state = MemoryStateStore(clock)
    window = _window(clock, state)
    await window.observe(_response(**{"RateLimit-Remaining": "0", "RateLimit-Reset": "60"}))
    # Regression: the server window resets but the local hour has not. The old code kept
    # blocking on the local counter until the hour ended.
    clock.advance(61.0)
    await window.acquire(1)
    await window.acquire(1)  # a fresh window takes two again


async def test_bad_server_header_is_ignored(clock: FakeClock) -> None:
    window = _window(clock, MemoryStateStore(clock))
    await window.observe(_response(**{"RateLimit-Remaining": "lots"}))
    await window.acquire(1)  # no exception


def test_registry_returns_the_same_limiters_per_key(clock: FakeClock) -> None:
    registry = RateLimiters(state=MemoryStateStore(clock), clock=clock)
    configs = [RateLimitConfig(window="second", limit=5)]
    assert registry.for_key("a", configs) is registry.for_key("a", configs)
    assert registry.for_key("a", configs) is not registry.for_key("b", configs)


async def test_clients_sharing_a_registry_share_one_quota(
    respx_mock: Any, clock: FakeClock
) -> None:
    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    state = MemoryStateStore(clock)
    shared = RateLimiters(state=state, clock=clock)
    cfg = parse_config(
        {
            "apis": {
                "demo": {
                    "base_url": BASE,
                    "rate_limits": [{"window": "hour", "limit": 2}],
                }
            }
        },
        env={},
    )
    api = cfg.api("demo")
    first = AsyncClient(api, state=state, rate_limiters=shared, clock=clock)
    second = AsyncClient(api, state=state, rate_limiters=shared, clock=clock)
    async with first, second:
        await first.get("/x")
        await second.get("/x")
        with pytest.raises(QuotaExhausted):
            await first.get("/x")
