"""Auth, retries and pagination over real HTTP: httpbin (docker) and JSONPlaceholder.

Run with `uv run pytest -m integration`. Retry backoff is shortened so the tests stay quick;
the unit tests cover the exact delays with a fake clock.
"""

from __future__ import annotations

import os

import pytest

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import HTTPStatusError, RetryExhausted
from apiframework.pagination import PagePagination

pytestmark = pytest.mark.integration

HTTPBIN = os.environ.get("HTTPBIN_URL", "http://localhost:8080")
JSONPLACEHOLDER = os.environ.get("JSONPLACEHOLDER_URL", "https://jsonplaceholder.typicode.com")
FAST_RETRY = {"max_attempts": 2, "backoff_base": 0.01, "max_backoff": 0.02}


async def test_bearer_token_is_accepted_by_the_server() -> None:
    cfg = parse_config(
        {"apis": {"echo": {"base_url": HTTPBIN, "auth": {"type": "bearer", "token": "${TOK}"}}}},
        env={"TOK": "abc123"},
    )
    async with AsyncClient(cfg.api("echo")) as client:
        response = await client.get("/bearer")
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["token"] == "abc123"


async def test_basic_auth_is_accepted_by_the_server() -> None:
    cfg = parse_config(
        {
            "apis": {
                "echo": {
                    "base_url": HTTPBIN,
                    "auth": {"type": "basic", "username": "${U}", "password": "${P}"},
                }
            }
        },
        env={"U": "alice", "P": "s3cret"},
    )
    async with AsyncClient(cfg.api("echo")) as client:
        response = await client.get("/basic-auth/alice/s3cret")
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"] == "alice"


async def test_missing_credentials_are_rejected_by_the_server() -> None:
    cfg = parse_config({"apis": {"echo": {"base_url": HTTPBIN}}}, env={})
    async with AsyncClient(cfg.api("echo")) as client:
        with pytest.raises(HTTPStatusError) as info:
            await client.get("/bearer")
    assert info.value.status_code == 401


async def test_server_503_is_retried_then_reported() -> None:
    cfg = parse_config(
        {"defaults": {"retry": FAST_RETRY}, "apis": {"echo": {"base_url": HTTPBIN}}},
        env={},
    )
    async with AsyncClient(cfg.api("echo")) as client:
        with pytest.raises(RetryExhausted) as info:
            await client.get("/status/503")
    assert info.value.attempts == 2
    assert isinstance(info.value.last_error, HTTPStatusError)
    assert info.value.last_error.status_code == 503


async def test_pagination_walks_every_jsonplaceholder_post() -> None:
    cfg = parse_config({"apis": {"jp": {"base_url": JSONPLACEHOLDER}}}, env={})
    async with AsyncClient(cfg.api("jp")) as client:
        spec = client.build_request("GET", "/posts", params={"_limit": 10, "_page": 1})
        items = [item async for item in client.iter_items(spec, PagePagination(page_param="_page"))]
    assert all(isinstance(item, dict) for item in items)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    assert len(ids) == 100
    assert len(set(ids)) == 100
