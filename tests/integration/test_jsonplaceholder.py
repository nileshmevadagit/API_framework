"""Integration tests against JSONPlaceholder (https://jsonplaceholder.typicode.com).

Runs only with `uv run pytest -m integration` (needs network access; no Docker).

JSONPlaceholder is the reference for every HTTP verb in the design doc. Until
AsyncClient exists these tests call httpx directly, so they pin the upstream
behaviour the framework tests will depend on. If one fails, the public API has
changed, not the library.

Known behaviour, per the live service:
- Writes (POST/PUT/PATCH/DELETE) are accepted and echoed but never stored, so a
  created record is 404 when read back.
- The docs don't list status codes; the values asserted here were observed live.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("JSONPLACEHOLDER_URL", "https://jsonplaceholder.typicode.com")
TIMEOUT = 10.0


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        yield client


@pytest.mark.parametrize(
    ("path", "expected_count"),
    [
        ("/users", 10),
        ("/posts", 100),
        ("/comments", 500),
        ("/albums", 100),
        ("/todos", 200),
    ],
)
async def test_list_resource_counts(api: httpx.AsyncClient, path: str, expected_count: int) -> None:
    resp = await api.get(path)
    assert resp.status_code == 200
    assert len(resp.json()) == expected_count


async def test_get_one_record(api: httpx.AsyncClient) -> None:
    resp = await api.get("/posts/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1
    assert body["userId"] == 1
    assert {"title", "body"} <= body.keys()


async def test_missing_record_is_404(api: httpx.AsyncClient) -> None:
    resp = await api.get("/posts/999999")
    assert resp.status_code == 404


async def test_nested_route_matches_filter(api: httpx.AsyncClient) -> None:
    nested = (await api.get("/posts/1/comments")).json()
    filtered = (await api.get("/comments", params={"postId": 1})).json()
    assert len(nested) == len(filtered) == 5
    assert all(c["postId"] == 1 for c in nested)


async def test_query_filter_on_posts(api: httpx.AsyncClient) -> None:
    resp = await api.get("/posts", params={"userId": 1})
    assert resp.status_code == 200
    posts = resp.json()
    assert posts
    assert all(p["userId"] == 1 for p in posts)


async def test_post_creates_and_echoes(api: httpx.AsyncClient) -> None:
    payload = {"title": "hello", "body": "world", "userId": 1}
    resp = await api.post("/posts", json=payload)
    assert resp.status_code == 201
    body: dict[str, Any] = resp.json()
    assert body["id"] == 101
    assert {k: body[k] for k in payload} == payload


async def test_put_replaces_and_echoes(api: httpx.AsyncClient) -> None:
    payload = {"id": 1, "title": "replaced", "body": "all fields", "userId": 1}
    resp = await api.put("/posts/1", json=payload)
    assert resp.status_code == 200
    assert resp.json() == payload


async def test_patch_merges_fields(api: httpx.AsyncClient) -> None:
    resp = await api.patch("/posts/1", json={"title": "patched"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "patched"
    assert body["id"] == 1
    assert "body" in body


async def test_delete_returns_empty_object(api: httpx.AsyncClient) -> None:
    resp = await api.delete("/posts/1")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_writes_are_not_persisted(api: httpx.AsyncClient) -> None:
    # Pins the caveat above: a created record cannot be read back.
    created = await api.post("/posts", json={"title": "t", "body": "b", "userId": 1})
    assert created.status_code == 201
    readback = await api.get(f"/posts/{created.json()['id']}")
    assert readback.status_code == 404
