"""End-to-end: config -> Client -> real HTTP. Needs httpbin (docker) and JSONPlaceholder.

Run with `uv run pytest -m integration`. These check what actually goes over the wire, which
the respx unit tests cannot.
"""

from __future__ import annotations

import os

import pytest

from apiframework.client import AsyncClient, Client
from apiframework.config import parse_config

pytestmark = pytest.mark.integration

HTTPBIN = os.environ.get("HTTPBIN_URL", "http://localhost:8080")
JSONPLACEHOLDER = os.environ.get("JSONPLACEHOLDER_URL", "https://jsonplaceholder.typicode.com")


async def test_configured_header_reaches_the_server() -> None:
    cfg = parse_config(
        {
            "apis": {
                "echo": {
                    "base_url": HTTPBIN,
                    "headers": {"X-Api-Key": "${DEMO_KEY}", "X-Client": "apiframework"},
                }
            }
        },
        env={"DEMO_KEY": "from-env-123"},
    )
    async with AsyncClient(cfg.api("echo")) as client:
        response = await client.get("/headers")
    sent = response.json()["headers"]
    # httpbin returns every header value as a list.
    assert sent["X-Api-Key"] == ["from-env-123"]
    assert sent["X-Client"] == ["apiframework"]


async def test_query_params_reach_the_server() -> None:
    cfg = parse_config({"apis": {"echo": {"base_url": HTTPBIN}}}, env={})
    async with AsyncClient(cfg.api("echo")) as client:
        response = await client.get("/anything", params={"page": 2, "active": True})
    # httpbin returns every query value as a list.
    assert response.json()["args"] == {"page": ["2"], "active": ["true"]}


def test_sync_client_against_jsonplaceholder() -> None:
    cfg = parse_config({"apis": {"jp": {"base_url": JSONPLACEHOLDER}}}, env={})
    with Client(cfg.api("jp")) as client:
        posts = client.get("/posts", params={"userId": 1}).json()
        created = client.post("/posts", json={"title": "t", "body": "b", "userId": 1})
    assert posts
    assert all(p["userId"] == 1 for p in posts)
    assert created.status_code == 201
