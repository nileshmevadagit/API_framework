"""Contract suite every StateStore must pass.

Memory and SQLite run as unit tests. Redis needs the docker-compose service, so it is marked
``integration`` and runs with ``pytest -m integration``. Each Redis test uses its own key prefix,
which is removed afterwards.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest

from apiframework.state import MemoryStateStore, RedisStateStore, SQLiteStateStore, StateStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from fakes import FakeClock

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

BACKENDS = [
    pytest.param("memory", id="memory"),
    pytest.param("sqlite", id="sqlite"),
    pytest.param("redis", id="redis", marks=pytest.mark.integration),
]


@pytest.fixture(params=BACKENDS)
async def store(
    request: pytest.FixtureRequest, tmp_path: Path, clock: FakeClock
) -> AsyncIterator[StateStore]:
    backend: str = request.param
    if backend == "memory":
        memory = MemoryStateStore(clock)
        yield memory
        return

    if backend == "sqlite":
        sqlite = SQLiteStateStore(tmp_path / "state.db", clock=clock)
        yield sqlite
        await sqlite.aclose()
        return

    prefix = f"contract-{uuid.uuid4().hex}:"
    redis_store = RedisStateStore(REDIS_URL, clock=clock, prefix=prefix)
    yield redis_store
    await _drop_prefix(prefix)
    await redis_store.aclose()


async def _drop_prefix(prefix: str) -> None:
    import redis.asyncio as redis_asyncio

    client = redis_asyncio.Redis.from_url(REDIS_URL)
    try:
        async for key in client.scan_iter(match=f"{prefix}*"):
            await client.delete(key)
    finally:
        await client.aclose()


async def test_missing_key_reads_as_none(store: StateStore) -> None:
    assert await store.get("nope") is None


async def test_set_then_get_round_trips_json(store: StateStore) -> None:
    value = {"token": "abc", "scopes": ["read"], "count": 3}
    await store.set("oauth", value)
    assert await store.get("oauth") == value


async def test_set_overwrites(store: StateStore) -> None:
    await store.set("k", "one")
    await store.set("k", "two")
    assert await store.get("k") == "two"


async def test_delete_removes_key_and_tolerates_missing(store: StateStore) -> None:
    await store.set("k", 1)
    await store.delete("k")
    await store.delete("k")
    assert await store.get("k") is None


async def test_incr_starts_at_amount_and_accumulates(store: StateStore) -> None:
    assert await store.incr("hits") == 1
    assert await store.incr("hits", 5) == 6
    assert await store.get("hits") == 6


async def test_incr_accepts_negative_amount(store: StateStore) -> None:
    await store.incr("tokens", 10)
    assert await store.incr("tokens", -4) == 6


async def test_incr_on_non_integer_raises(store: StateStore) -> None:
    await store.set("name", "alice")
    with pytest.raises(TypeError):
        await store.incr("name")


async def test_incr_on_bool_raises(store: StateStore) -> None:
    await store.set("flag", True)
    with pytest.raises(TypeError):
        await store.incr("flag")


async def test_expired_key_reads_as_missing(store: StateStore, clock: FakeClock) -> None:
    await store.set("tok", "x", expires_at=clock.now() + 60)
    clock.advance(59)
    assert await store.get("tok") == "x"
    clock.advance(1)
    assert await store.get("tok") is None


async def test_expired_counter_restarts_from_zero(store: StateStore, clock: FakeClock) -> None:
    window_end = clock.now() + 3600
    assert await store.incr("hour", 5, expires_at=window_end) == 5
    clock.advance(3600)
    assert await store.incr("hour", 1, expires_at=window_end + 3600) == 1


async def test_counter_window_expiry_is_fixed_at_creation(
    store: StateStore, clock: FakeClock
) -> None:
    window_end = clock.now() + 100
    await store.incr("win", 1, expires_at=window_end)
    # A later call passing a far-off expiry must not extend the window.
    await store.incr("win", 1, expires_at=window_end + 10_000)
    clock.advance(100)
    assert await store.get("win") is None


async def test_returned_values_are_copies(store: StateStore) -> None:
    await store.set("doc", {"items": [1]})
    fetched = await store.get("doc")
    assert isinstance(fetched, dict)
    fetched["items"] = [999]
    assert await store.get("doc") == {"items": [1]}
