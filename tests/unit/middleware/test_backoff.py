from __future__ import annotations

import email.utils
import random

import pytest

from apiframework.config import RetryConfig
from apiframework.middleware.backoff import backoff_delay, parse_retry_after

NOW = 1_700_000_000.0


class MaxJitter:
    """Stands in for random.Random and always picks the top of the range."""

    def uniform(self, low: float, high: float) -> float:
        return high


@pytest.mark.parametrize(
    ("header", "expected"),
    [("120", 120.0), (" 2.5 ", 2.5), ("0", 0.0), ("-5", 0.0)],
)
def test_retry_after_in_seconds(header: str, expected: float) -> None:
    assert parse_retry_after(header, NOW) == expected


def test_retry_after_http_date_in_the_future() -> None:
    when = email.utils.formatdate(NOW + 90, usegmt=True)
    assert parse_retry_after(when, NOW) == pytest.approx(90.0, abs=1.0)


def test_retry_after_http_date_in_the_past_is_zero() -> None:
    when = email.utils.formatdate(NOW - 90, usegmt=True)
    assert parse_retry_after(when, NOW) == 0.0


@pytest.mark.parametrize("header", ["soon", "", "nan", "inf"])
def test_unparseable_retry_after_is_none(header: str) -> None:
    assert parse_retry_after(header, NOW) is None


def test_backoff_doubles_then_caps() -> None:
    config = RetryConfig(backoff_base=0.5, max_backoff=4.0)
    delays = [backoff_delay(attempt, config, MaxJitter()) for attempt in range(1, 6)]
    assert delays == [0.5, 1.0, 2.0, 4.0, 4.0]


def test_backoff_jitter_stays_within_ceiling() -> None:
    config = RetryConfig(backoff_base=1.0, max_backoff=8.0)
    rng = random.Random(42)
    for attempt in range(1, 10):
        ceiling = min(8.0, 1.0 * 2 ** (attempt - 1))
        assert 0.0 <= backoff_delay(attempt, config, rng) <= ceiling
