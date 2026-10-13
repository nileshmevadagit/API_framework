"""SQLite-specific behaviour: durability across instances and concurrent counters."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from apiframework.state import SQLiteStateStore

if TYPE_CHECKING:
    from pathlib import Path

    from fakes import FakeClock


async def test_values_survive_a_new_store_on_the_same_file(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "state.db"
    first = SQLiteStateStore(path, clock=clock)
    await first.set("token", {"access": "abc"}, expires_at=clock.now() + 600)
    await first.incr("hits", 3)
    await first.aclose()

    second = SQLiteStateStore(path, clock=clock)
    assert await second.get("token") == {"access": "abc"}
    assert await second.incr("hits", 1) == 4
    await second.aclose()


async def test_concurrent_increments_are_not_lost(tmp_path: Path, clock: FakeClock) -> None:
    store = SQLiteStateStore(tmp_path / "state.db", clock=clock)
    await asyncio.gather(*(store.incr("quota") for _ in range(50)))
    assert await store.get("quota") == 50
    await store.aclose()


async def test_two_stores_on_one_file_share_a_counter(tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "state.db"
    left = SQLiteStateStore(path, clock=clock)
    right = SQLiteStateStore(path, clock=clock)
    await asyncio.gather(
        *(left.incr("shared") for _ in range(20)), *(right.incr("shared") for _ in range(20))
    )
    assert await left.get("shared") == 40
    await left.aclose()
    await right.aclose()
