"""In-memory StateStore. The default. Lost on exit, so use SQLite or Redis for durable quotas."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apiframework.clock import Clock, SystemClock

if TYPE_CHECKING:
    from pydantic import JsonValue


@dataclass
class _Entry:
    value: JsonValue
    expires_at: float | None


class MemoryStateStore:
    """Single-process store. Each instance owns its data, so two stores never share state.

    The methods have no ``await`` inside, so each one runs to completion on the event
    loop without interleaving. That makes ``incr`` atomic without a lock.
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._data: dict[str, _Entry] = {}

    def _live(self, key: str) -> _Entry | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and self._clock.now() >= entry.expires_at:
            del self._data[key]
            return None
        return entry

    async def get(self, key: str) -> JsonValue | None:
        entry = self._live(key)
        return None if entry is None else copy.deepcopy(entry.value)

    async def set(self, key: str, value: JsonValue, *, expires_at: float | None = None) -> None:
        self._data[key] = _Entry(copy.deepcopy(value), expires_at)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, amount: int = 1, *, expires_at: float | None = None) -> int:
        entry = self._live(key)
        if entry is None:
            self._data[key] = _Entry(amount, expires_at)
            return amount
        current = entry.value
        if isinstance(current, bool) or not isinstance(current, int):
            raise TypeError(f"state key {key!r} does not hold an integer")
        entry.value = current + amount
        return current + amount
