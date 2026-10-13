from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.clock import Clock, SystemClock

if TYPE_CHECKING:
    from fakes import FakeClock


def test_system_clock_satisfies_clock_protocol() -> None:
    clock: Clock = SystemClock()
    assert clock.now() > 1_600_000_000  # a real epoch time, not zero
    assert clock.monotonic() >= 0


async def test_fake_clock_sleep_advances_time_without_waiting(clock: FakeClock) -> None:
    start = clock.now()
    await clock.sleep(30)
    assert clock.now() == start + 30
    assert clock.slept == [30]
