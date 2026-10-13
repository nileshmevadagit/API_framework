"""Auth handlers, the factory, and the auth middleware. HTTP mocked with respx."""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.auth import (
    ApiKeyAuth,
    BasicAuth,
    BearerAuth,
    CustomAuth,
    OAuth2Auth,
    build_auth,
)
from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import AuthError
from apiframework.request import RequestSpec
from apiframework.state import MemoryStateStore

if TYPE_CHECKING:
    import respx

    from fakes import FakeClock

BASE = "https://api.test/v1"
TOKEN_URL = "https://auth.test/token"


def _spec(**kwargs: Any) -> RequestSpec:
    return RequestSpec(method="GET", url=f"{BASE}/me", **kwargs)


async def test_api_key_in_header() -> None:
    out = await ApiKeyAuth("X-Api-Key", "k1").apply(_spec())
    assert ("X-Api-Key", "k1") in out.headers


async def test_api_key_in_query() -> None:
    out = await ApiKeyAuth("api_key", "k1", location="query").apply(_spec())
    assert ("api_key", "k1") in out.params
    assert ("X-Api-Key", "k1") not in out.headers


async def test_bearer_sets_authorization() -> None:
    out = await BearerAuth("tok").apply(_spec())
    assert ("Authorization", "Bearer tok") in out.headers


async def test_new_credential_replaces_an_existing_header_of_the_same_name() -> None:
    req = _spec(headers={"authorization": "Bearer old"})
    out = await BearerAuth("new").apply(req)
    assert [v for k, v in out.headers if k.lower() == "authorization"] == ["Bearer new"]


async def test_basic_encodes_user_and_password() -> None:
    out = await BasicAuth("alice", "s3cret").apply(_spec())
    expected = base64.b64encode(b"alice:s3cret").decode()
    assert ("Authorization", f"Basic {expected}") in out.headers


async def test_custom_auth_accepts_sync_and_async_functions() -> None:
    def sync_sign(req: RequestSpec) -> RequestSpec:
        return req.clone(headers=(("X-Sig", "sync"),))

    async def async_sign(req: RequestSpec) -> RequestSpec:
        return req.clone(headers=(("X-Sig", "async"),))

    assert ("X-Sig", "sync") in (await CustomAuth(sync_sign).apply(_spec())).headers
    assert ("X-Sig", "async") in (await CustomAuth(async_sign).apply(_spec())).headers


def test_build_auth_maps_each_config_type() -> None:
    cfg = parse_config(
        {
            "apis": {
                "bearer": {"base_url": BASE, "auth": {"type": "bearer", "token": "${T}"}},
                "key": {
                    "base_url": BASE,
                    "auth": {"type": "api_key", "name": "K", "value": "${K}"},
                },
                "basic": {
                    "base_url": BASE,
                    "auth": {"type": "basic", "username": "${U}", "password": "${P}"},
                },
                "oauth": {
                    "base_url": BASE,
                    "auth": {
                        "type": "oauth2",
                        "token_url": TOKEN_URL,
                        "client_id": "${ID}",
                        "client_secret": "${SECRET}",
                    },
                },
                "none": {"base_url": BASE, "auth": {"type": "none"}},
                "unset": {"base_url": BASE},
            }
        },
        env={"T": "t", "K": "k", "U": "u", "P": "p", "ID": "i", "SECRET": "s"},
    )
    env_clock = _StubClock()
    state = MemoryStateStore(env_clock)
    kinds = {
        name: build_auth(cfg.api(name).auth, clock=env_clock, state=state)
        for name in ("bearer", "key", "basic", "oauth", "none", "unset")
    }
    assert isinstance(kinds["bearer"], BearerAuth)
    assert isinstance(kinds["key"], ApiKeyAuth)
    assert isinstance(kinds["basic"], BasicAuth)
    assert isinstance(kinds["oauth"], OAuth2Auth)
    assert kinds["none"] is None
    assert kinds["unset"] is None


class _StubClock:
    def now(self) -> float:
        return 1_700_000_000.0

    def monotonic(self) -> float:
        return 0.0

    async def sleep(self, seconds: float) -> None:
        return None


def _oauth(clock: FakeClock, **kwargs: Any) -> OAuth2Auth:
    return OAuth2Auth(
        token_url=TOKEN_URL,
        client_id="id",
        client_secret="secret",
        clock=clock,
        state=MemoryStateStore(clock),
        **kwargs,
    )


async def test_oauth2_fetches_and_caches_token(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    token_route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t1", "expires_in": 3600})
    )
    handler = _oauth(clock)
    first = await handler.apply(_spec())
    second = await handler.apply(_spec())
    assert ("Authorization", "Bearer t1") in first.headers
    assert ("Authorization", "Bearer t1") in second.headers
    assert token_route.call_count == 1


async def test_oauth2_sends_client_credentials(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t1"})
    )
    await _oauth(clock, scope="read:all").apply(_spec())
    body = route.calls.last.request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "scope=read%3Aall" in body
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")


async def test_oauth2_refreshes_before_expiry(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "t1", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "t2", "expires_in": 3600}),
        ]
    )
    handler = _oauth(clock, refresh_margin=60.0)
    await handler.apply(_spec())
    clock.advance(3600 - 30)  # inside the 60 second margin
    refreshed = await handler.apply(_spec())
    assert ("Authorization", "Bearer t2") in refreshed.headers


async def test_oauth2_concurrent_expiry_triggers_one_refresh(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t1", "expires_in": 3600})
    )
    handler = _oauth(clock)
    results = await asyncio.gather(*(handler.apply(_spec()) for _ in range(8)))
    assert route.call_count == 1
    assert all(("Authorization", "Bearer t1") in r.headers for r in results)


async def test_oauth2_token_failure_is_an_auth_error(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(401, text="secret echo"))
    with pytest.raises(AuthError, match="HTTP 401") as info:
        await _oauth(clock).apply(_spec())
    assert "secret echo" not in str(info.value)


@pytest.mark.parametrize(
    "body",
    [{"expires_in": 60}, {"access_token": ""}, {"access_token": "t", "expires_in": -1}],
)
async def test_oauth2_malformed_token_response_is_an_auth_error(
    respx_mock: respx.MockRouter, clock: FakeClock, body: dict[str, Any]
) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(AuthError):
        await _oauth(clock).apply(_spec())


async def test_oauth2_unauthorized_drops_token_and_retries_once(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    token_route = respx_mock.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "old", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "new", "expires_in": 3600}),
        ]
    )
    api = respx_mock.get(f"{BASE}/me").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
    )
    cfg = parse_config({"apis": {"demo": {"base_url": BASE}}}, env={})
    async with AsyncClient(cfg.api("demo"), auth=_oauth(clock), clock=clock) as client:
        response = await client.get("/me")

    assert response.status_code == 200
    assert token_route.call_count == 2
    assert api.calls[0].request.headers["Authorization"] == "Bearer old"
    assert api.calls[1].request.headers["Authorization"] == "Bearer new"


async def test_persistent_401_is_not_retried_forever(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    from apiframework.errors import HTTPStatusError

    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
    )
    api = respx_mock.get(f"{BASE}/me").mock(return_value=httpx.Response(401))
    cfg = parse_config({"apis": {"demo": {"base_url": BASE}}}, env={})
    async with AsyncClient(cfg.api("demo"), auth=_oauth(clock), clock=clock) as client:
        with pytest.raises(HTTPStatusError):
            await client.get("/me")
    assert api.call_count == 2  # one attempt, one refresh-and-retry, then give up
