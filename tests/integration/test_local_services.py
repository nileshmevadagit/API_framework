"""Integration smoke test: proves docker-compose services are reachable.

Runs only with `uv run pytest -m integration` after `docker compose up -d`.
Replace with real client tests once AsyncClient exists.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration

HTTPBIN = os.environ.get("HTTPBIN_URL", "http://localhost:8080")


async def test_httpbin_is_up() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{HTTPBIN}/status/200")
    assert resp.status_code == 200
