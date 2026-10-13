"""Retry middleware through a real AsyncClient, with HTTP mocked by respx and a fake clock."""

from __future__ import annotations

import email.utils
import random
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import HTTPStatusError, ResponseRejected, RetryExhausted
from apiframework.middleware.classify import Verdict

if TYPE_CHECKING:
    import respx

    from fakes import FakeClock

BASE = "https://api.test/v1"


def _client(clock: FakeClock, *, retry: dict[str, Any] | None = None, **kwargs: Any) -> AsyncClient:
    cfg = parse_config(
        {
            "defaults": {"retry": retry or {"max_attempts": 4, "backoff_base": 0.5}},
            "apis": {"demo": {"base_url": BASE}},
        },
        env={},
    )
    return AsyncClient(cfg.api("demo"), clock=clock, rng=random.Random(7), **kwargs)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
async def test_each_retryable_status_is_retried(
    respx_mock: respx.MockRouter, clock: FakeClock, status: int
) -> None:
    route = respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(status), httpx.Response(200)]
    )
    async with _client(clock) as client:
        response = await client.get("/x")
    assert response.status_code == 200
    assert route.call_count == 2
    assert len(clock.slept) == 1


async def test_retry_after_seconds_overrides_backoff(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
    )
    async with _client(clock) as client:
        await client.get("/x")
    assert clock.slept == [7.0]


async def test_retry_after_http_date_overrides_backoff(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    when = email.utils.formatdate(clock.now() + 120, usegmt=True)
    respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": when}), httpx.Response(200)]
    )
    async with _client(clock) as client:
        await client.get("/x")
    assert clock.slept == pytest.approx([120.0], abs=1.0)


async def test_unparseable_retry_after_falls_back_to_backoff(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": "soon"}), httpx.Response(200)]
    )
    async with _client(clock) as client:
        await client.get("/x")
    assert len(clock.slept) == 1
    assert 0.0 <= clock.slept[0] <= 0.5  # first retry: backoff_base * 1, full jitter


async def test_non_retryable_4xx_fails_immediately(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    route = respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(404))
    async with _client(clock) as client:
        with pytest.raises(HTTPStatusError) as info:
            await client.get("/x")
    assert info.value.status_code == 404
    assert route.call_count == 1
    assert clock.slept == []


async def test_exhausted_budget_raises_retry_exhausted(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    route = respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(503))
    async with _client(clock, retry={"max_attempts": 3}) as client:
        with pytest.raises(RetryExhausted) as info:
            await client.get("/x")
    assert info.value.attempts == 3
    assert isinstance(info.value.last_error, HTTPStatusError)
    assert route.call_count == 3
    assert len(clock.slept) == 2


async def test_connection_error_is_retried(respx_mock: respx.MockRouter, clock: FakeClock) -> None:
    respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(200)]
    )
    async with _client(clock) as client:
        response = await client.get("/x")
    assert response.status_code == 200


async def test_read_timeout_on_get_is_retried(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.get(f"{BASE}/x").mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200)])
    async with _client(clock) as client:
        assert (await client.get("/x")).status_code == 200


async def test_post_is_not_retried_by_default(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    route = respx_mock.post(f"{BASE}/x").mock(return_value=httpx.Response(503))
    async with _client(clock) as client:
        with pytest.raises(RetryExhausted) as info:
            await client.post("/x", json={"a": 1})
    assert info.value.attempts == 1
    assert route.call_count == 1


async def test_post_is_not_retried_after_a_read_timeout(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    # The server may have created the record before the timeout, so a blind retry is unsafe.
    route = respx_mock.post(f"{BASE}/x").mock(side_effect=httpx.ReadTimeout("slow"))
    async with _client(clock) as client:
        with pytest.raises(RetryExhausted):
            await client.post("/x", json={"a": 1})
    assert route.call_count == 1


async def test_post_with_idempotency_key_is_retried(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.post(f"{BASE}/x").mock(side_effect=[httpx.Response(503), httpx.Response(201)])
    async with _client(clock) as client:
        response = await client.post("/x", json={}, headers={"Idempotency-Key": "k-1"})
    assert response.status_code == 201


async def test_post_retries_with_explicit_opt_in(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.post(f"{BASE}/x").mock(side_effect=[httpx.Response(502), httpx.Response(201)])
    async with _client(clock, retry={"retry_non_idempotent": True}) as client:
        assert (await client.post("/x", json={})).status_code == 201


async def test_body_error_on_200_is_rejected_by_classifier(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    class BodyErrors:
        def classify(self, response: httpx.Response) -> Verdict:
            return Verdict.FAILURE if "errors" in response.json() else Verdict.OK

    respx_mock.post(f"{BASE}/graphql").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "bad"}]})
    )
    async with _client(clock, classifier=BodyErrors()) as client:
        with pytest.raises(ResponseRejected):
            await client.post("/graphql", json={"query": "{x}"})


async def test_every_retry_gets_a_fresh_credential(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    from apiframework.auth import CustomAuth

    tokens = iter(["t1", "t2", "t3"])
    seen: list[str] = []
    respx_mock.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200)]
    )

    def rotate(req: Any) -> Any:
        token = next(tokens)
        seen.append(token)
        return req.clone(headers=(("Authorization", f"Bearer {token}"),))

    async with _client(clock, auth=CustomAuth(rotate)) as client:
        await client.get("/x")
    assert seen == ["t1", "t2", "t3"]
