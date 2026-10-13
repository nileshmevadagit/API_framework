"""Test doubles. Import as ``from fakes import ...``; tests/ is on sys.path."""

from __future__ import annotations


class FakeClock:
    """Clock that only moves when told to. ``sleep`` advances time instead of waiting."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self._now += seconds

    def advance(self, seconds: float) -> None:
        self._now += seconds
