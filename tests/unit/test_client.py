"""Client behaviour with HTTP mocked by respx. No real network."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.client import AsyncClient, Client
from apiframework.config import parse_config
from apiframework.errors import HTTPStatusError, RetryExhausted

if TYPE_CHECKING:
    import respx

    from apiframework.request import RequestSpec

BASE = "https://api.test/v1"


def _api(**extra: Any) -> Any:
    cfg = parse_config({"apis": {"demo": {"base_url": BASE, **extra}}}, env={})
    return cfg.api("demo")


async def test_path_is_joined_to_base_url_without_double_slashes(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get(f"{BASE}/users").mock(return_value=httpx.Response(200))
    async with AsyncClient(_api()) as client:
        await client.get("/users")
    assert route.called


async def test_query_params_are_stringified(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE}/search").mock(return_value=httpx.Response(200))
    async with AsyncClient(_api()) as client:
        await client.get("/search", params={"page": 2, "active": True, "q": "a b"})
    sent = route.calls.last.request.url.params
    assert sent["page"] == "2"
    assert sent["active"] == "true"
    assert sent["q"] == "a b"


async def test_configured_headers_are_sent_and_request_headers_override(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get(f"{BASE}/me").mock(return_value=httpx.Response(200))
    api = _api(headers={"Accept": "application/json", "X-Version": "1"})
    async with AsyncClient(api) as client:
        await client.get("/me", headers={"X-Version": "2"})
    sent = route.calls.last.request.headers
    assert sent["Accept"] == "application/json"
    assert sent["X-Version"] == "2"


async def test_json_body_is_encoded(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE}/posts").mock(return_value=httpx.Response(201))
    async with AsyncClient(_api()) as client:
        response = await client.post("/posts", json={"title": "t", "userId": 1})
    assert response.status_code == 201
    assert json.loads(route.calls.last.request.content) == {"title": "t", "userId": 1}


async def test_raw_content_is_sent_as_is(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.put(f"{BASE}/blob").mock(return_value=httpx.Response(200))
    async with AsyncClient(_api()) as client:
        await client.put("/blob", content=b"\x00\x01")
    assert route.calls.last.request.content == b"\x00\x01"


@pytest.mark.parametrize(
    ("method", "call"),
    [
        ("GET", lambda c: c.get("/r")),
        ("HEAD", lambda c: c.head("/r")),
        ("POST", lambda c: c.post("/r", json={})),
        ("PUT", lambda c: c.put("/r", json={})),
        ("PATCH", lambda c: c.patch("/r", json={})),
        ("DELETE", lambda c: c.delete("/r")),
    ],
)
async def test_every_verb_uses_its_method(
    respx_mock: respx.MockRouter, method: str, call: Any
) -> None:
    route = respx_mock.route(url=f"{BASE}/r").mock(return_value=httpx.Response(200))
    async with AsyncClient(_api()) as client:
        await call(client)
    assert route.calls.last.request.method == method


async def test_json_and_content_together_are_rejected() -> None:
    async with AsyncClient(_api()) as client:
        with pytest.raises(ValueError, match="not both"):
            await client.request("POST", "/r", json={}, content=b"x")


async def test_success_responses_are_returned_as_received(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/ok").mock(return_value=httpx.Response(201, text="made"))
    async with AsyncClient(_api()) as client:
        response = await client.get("/ok")
    assert response.status_code == 201
    assert response.text == "made"


async def test_retryable_error_is_raised_after_retries(
    respx_mock: respx.MockRouter, clock: Any
) -> None:
    route = respx_mock.get(f"{BASE}/boom").mock(return_value=httpx.Response(500, text="nope"))
    api = parse_config(
        {"defaults": {"retry": {"max_attempts": 2}}, "apis": {"demo": {"base_url": BASE}}},
        env={},
    ).api("demo")
    async with AsyncClient(api, clock=clock) as client:
        with pytest.raises(RetryExhausted) as info:
            await client.get("/boom")
    assert info.value.attempts == 2
    assert route.call_count == 2


async def test_client_error_is_raised_without_retry(
    respx_mock: respx.MockRouter, clock: Any
) -> None:
    route = respx_mock.get(f"{BASE}/missing").mock(return_value=httpx.Response(404))
    async with AsyncClient(_api(), clock=clock) as client:
        with pytest.raises(HTTPStatusError):
            await client.get("/missing")
    assert route.call_count == 1


async def test_middleware_wraps_requests_in_order(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    seen: list[str] = []

    async def outer(req: RequestSpec, call_next: Any) -> httpx.Response:
        seen.append("outer")
        return await call_next(req.clone(headers={"X-Trace": "1"}))

    async def inner(req: RequestSpec, call_next: Any) -> httpx.Response:
        seen.append("inner")
        return await call_next(req)

    async with AsyncClient(_api(), middleware=[outer, inner]) as client:
        await client.get("/x")

    assert seen == ["outer", "inner"]
    assert route.calls.last.request.headers["X-Trace"] == "1"


async def test_two_clients_do_not_share_headers(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://a.test/x").mock(return_value=httpx.Response(200))
    respx_mock.get("https://b.test/x").mock(return_value=httpx.Response(200))
    a = parse_config({"apis": {"a": {"base_url": "https://a.test", "headers": {"X-Who": "a"}}}})
    b = parse_config({"apis": {"b": {"base_url": "https://b.test"}}})
    async with AsyncClient(a.api("a")) as ca, AsyncClient(b.api("b")) as cb:
        r_a = await ca.get("/x")
        r_b = await cb.get("/x")
    assert r_a.request.headers["X-Who"] == "a"
    assert "X-Who" not in r_b.request.headers


def test_sync_client_wraps_async_behaviour(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=[1, 2]))
    with Client(_api()) as client:
        response = client.get("/items", params={"limit": 2})
    assert response.json() == [1, 2]


def test_sync_client_post_and_delete(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{BASE}/items").mock(return_value=httpx.Response(201, json={"id": 7}))
    respx_mock.delete(f"{BASE}/items/7").mock(return_value=httpx.Response(204))
    with Client(_api()) as client:
        created = client.post("/items", json={"name": "x"})
        deleted = client.delete("/items/7")
    assert created.json() == {"id": 7}
    assert deleted.status_code == 204
