"""Behaviour specific to the in-memory store. Shared behaviour lives in test_store_contract.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.state import MemoryStateStore

if TYPE_CHECKING:
    from fakes import FakeClock


async def test_two_instances_do_not_share_state(clock: FakeClock) -> None:
    first = MemoryStateStore(clock)
    second = MemoryStateStore(clock)
    await first.set("k", "only-in-first")
    assert await second.get("k") is None


async def test_defaults_to_system_clock_when_none_given() -> None:
    store = MemoryStateStore()
    await store.set("k", 1, expires_at=0)  # already in the past by the system clock
    assert await store.get("k") is None


async def test_set_copies_input_so_later_mutation_does_not_leak() -> None:
    store = MemoryStateStore()
    value: dict[str, list[int]] = {"items": [1]}
    await store.set("doc", value)
    value["items"].append(2)
    assert await store.get("doc") == {"items": [1]}
