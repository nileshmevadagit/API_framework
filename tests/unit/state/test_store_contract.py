"""Contract suite every StateStore must pass. SQLite and Redis join FACTORIES later."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from apiframework.clock import Clock
from apiframework.state import MemoryStateStore, StateStore

if TYPE_CHECKING:
    from fakes import FakeClock

StoreFactory = Callable[[Clock], StateStore]

FACTORIES: list[StoreFactory] = [
    lambda clock: MemoryStateStore(clock),
]


@pytest.fixture(params=FACTORIES, ids=["memory"])
def make_store(request: pytest.FixtureRequest) -> StoreFactory:
    factory: StoreFactory = request.param
    return factory


@pytest.fixture
def store(make_store: StoreFactory, clock: FakeClock) -> StateStore:
    return make_store(clock)


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
