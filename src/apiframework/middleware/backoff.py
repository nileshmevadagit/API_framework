"""Backoff and Retry-After. Pure functions: the random source and clock are passed in."""

from __future__ import annotations

import email.utils
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random

    from apiframework.config import RetryConfig


def backoff_delay(attempt: int, config: RetryConfig, rng: random.Random) -> float:
    """Exponential backoff with full jitter. ``attempt`` counts from 1 (the first retry)."""
    exponent = min(attempt - 1, 60)  # keep the power bounded; max_backoff caps it anyway
    ceiling = min(config.max_backoff, config.backoff_base * (2**exponent))
    return rng.uniform(0.0, ceiling)


def parse_retry_after(value: str, now: float) -> float | None:
    """Seconds to wait from a ``Retry-After`` header, or None if it cannot be parsed.

    Accepts both forms in RFC 9110: delay-seconds and an HTTP-date. ``now`` is epoch
    seconds, used to turn a date into a delay.
    """
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        pass
    else:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - now)
