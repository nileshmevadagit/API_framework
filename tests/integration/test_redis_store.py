"""Redis store across separate connections, the case it exists for. Needs docker-compose redis."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from apiframework.clock import SystemClock
from apiframework.state import RedisStateStore

pytestmark = pytest.mark.integration

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def test_two_workers_share_one_counter() -> None:
    prefix = f"itest-{uuid.uuid4().hex}:"
    clock = SystemClock()
    worker_a = RedisStateStore(REDIS_URL, clock=clock, prefix=prefix)
    worker_b = RedisStateStore(REDIS_URL, clock=clock, prefix=prefix)
    try:
        await asyncio.gather(
            *(worker_a.incr("quota", expires_at=clock.now() + 60) for _ in range(25)),
            *(worker_b.incr("quota", expires_at=clock.now() + 60) for _ in range(25)),
        )
        assert await worker_a.get("quota") == 50
        assert await worker_b.get("quota") == 50
    finally:
        await worker_a.delete("quota")
        await worker_a.aclose()
        await worker_b.aclose()


async def test_expired_value_is_missing_for_every_worker() -> None:
    prefix = f"itest-{uuid.uuid4().hex}:"
    clock = SystemClock()
    worker_a = RedisStateStore(REDIS_URL, clock=clock, prefix=prefix)
    worker_b = RedisStateStore(REDIS_URL, clock=clock, prefix=prefix)
    try:
        # Already expired, so no waiting is needed: the expiry check runs on read.
        await worker_a.set("token", "t", expires_at=clock.now() - 1)
        assert await worker_b.get("token") is None
    finally:
        await worker_a.delete("token")
        await worker_a.aclose()
        await worker_b.aclose()
