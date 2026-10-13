"""Time source. Injected everywhere so tests never sleep and never read the real clock."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    """Wall time, monotonic time and sleeping, behind one object so tests can fake all three."""

    def now(self) -> float:
        """Seconds since the Unix epoch. Used for quota reset times."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds. Used for token buckets and durations."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the current task for ``seconds``."""
        ...


class SystemClock:
    """The real clock. This is the default outside tests."""

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
