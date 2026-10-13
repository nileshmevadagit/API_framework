"""Clients. ``AsyncClient`` holds the logic; ``Client`` is a thin sync wrapper over it.

One client talks to one API. Each client owns its connection pool, so two clients in
one process never share state. Call ``aclose()`` / ``close()`` when you are done, or
use the client as a context manager.

The chain is fixed: caller middleware (outermost), retry, auth, rate limits, transport.
Retries therefore get a fresh credential and are counted against quota. Non-2xx responses
are raised as ``HTTPStatusError`` after retries are exhausted or ruled out.
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, TypeVar

from apiframework.auth import build_auth
from apiframework.clock import SystemClock
from apiframework.middleware.access_log import AccessLogMiddleware
from apiframework.middleware.auth import AuthMiddleware
from apiframework.middleware.chain import build_chain
from apiframework.middleware.ratelimit import RateLimitMiddleware
from apiframework.middleware.retry import RetryMiddleware
from apiframework.middleware.telemetry import TelemetryMiddleware, get_tracer
from apiframework.pagination import iter_items, iter_pages
from apiframework.ratelimit import RateLimiters
from apiframework.request import RequestSpec
from apiframework.state import MemoryStateStore
from apiframework.transport import HTTPTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
    from types import TracebackType

    import httpx
    from pydantic import JsonValue
    from typing_extensions import Self

    from apiframework.auth.base import AuthHandler
    from apiframework.clock import Clock
    from apiframework.config import ResolvedApi
    from apiframework.hooks import Hooks
    from apiframework.middleware.base import Middleware
    from apiframework.middleware.classify import Classifier
    from apiframework.pagination.base import PaginationStrategy
    from apiframework.request import HTTPMethod
    from apiframework.state import StateStore

ParamValue = str | int | float | bool
T = TypeVar("T")


def _param_text(value: ParamValue) -> str:
    # Query strings use lowercase booleans, not Python's True/False.
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class AsyncClient:
    """Async client for one API. Use ``await client.get(...)`` and friends."""

    def __init__(
        self,
        api: ResolvedApi,
        *,
        middleware: Sequence[Middleware] = (),
        auth: AuthHandler | None = None,
        classifier: Classifier | None = None,
        state: StateStore | None = None,
        rate_limiters: RateLimiters | None = None,
        clock: Clock | None = None,
        rng: random.Random | None = None,
        hooks: Hooks | None = None,
        log_bodies: bool = False,
        telemetry: bool = False,
    ) -> None:
        """Build the client for ``api``.

        ``auth`` overrides the auth in the config (for custom handlers). ``state`` and
        ``rate_limiters`` default to private ones; pass shared instances to share quota.
        ``clock`` and ``rng`` are for tests. ``hooks`` receive metrics events.
        ``log_bodies`` adds request and response bodies to DEBUG logs. ``telemetry`` starts an
        OpenTelemetry span per call (needs the ``otel`` extra).
        """
        self.name = api.name
        self._base_url = api.base_url.rstrip("/")
        clock = clock if clock is not None else SystemClock()
        state = state if state is not None else MemoryStateStore(clock)
        rng = rng if rng is not None else random.Random()
        self._transport = HTTPTransport(api)

        handler = auth if auth is not None else build_auth(api.auth, clock=clock, state=state)
        limiters = (
            rate_limiters if rate_limiters is not None else RateLimiters(state=state, clock=clock)
        )
        layers: list[Middleware] = [*middleware]
        if telemetry:
            layers.append(TelemetryMiddleware(api=api.name, tracer=get_tracer()))
        layers.append(AccessLogMiddleware(api=api.name, hooks=hooks, log_bodies=log_bodies))
        layers.append(
            RetryMiddleware(
                api.retry,
                clock=clock,
                rng=rng,
                classifier=classifier,
                api=api.name,
                hooks=hooks,
            )
        )
        if handler is not None:
            layers.append(AuthMiddleware(handler))
        limits = limiters.for_key(api.name, api.rate_limits)
        if limits:
            layers.append(RateLimitMiddleware(limits, clock=clock, api=api.name, hooks=hooks))
        self._chain = build_chain(layers, self._transport.send)

    async def send(self, spec: RequestSpec) -> httpx.Response:
        """Send a prepared request through the middleware chain."""
        return await self._chain(spec)

    def build_request(
        self,
        method: HTTPMethod,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        cost: int = 1,
        url_template: str | None = None,
    ) -> RequestSpec:
        """Build a request for ``path`` (relative to the API's base URL) without sending it.

        Pass ``json`` or ``content``, not both. ``cost`` is how many quota units it uses.
        """
        if json is not None and content is not None:
            raise ValueError("pass json or content, not both")
        return RequestSpec(
            method=method,
            url=self._url(path),
            url_template=url_template or path,
            params=tuple((key, _param_text(value)) for key, value in (params or {}).items()),
            headers=tuple((key, value) for key, value in (headers or {}).items()),
            json_body=json,
            content=content,
            cost=cost,
        )

    async def request(
        self,
        method: HTTPMethod,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        cost: int = 1,
        url_template: str | None = None,
    ) -> httpx.Response:
        """Build a request for ``path`` and send it through the chain."""
        spec = self.build_request(
            method,
            path,
            params=params,
            headers=headers,
            json=json,
            content=content,
            cost=cost,
            url_template=url_template,
        )
        return await self.send(spec)

    def iter_pages(
        self,
        spec: RequestSpec,
        strategy: PaginationStrategy,
        *,
        max_pages: int | None = None,
    ) -> AsyncIterator[httpx.Response]:
        """Yield each page for ``spec``, following ``strategy`` until the last page."""
        return iter_pages(self.send, spec, strategy, max_pages=max_pages)

    def iter_items(
        self,
        spec: RequestSpec,
        strategy: PaginationStrategy,
        *,
        max_pages: int | None = None,
    ) -> AsyncIterator[JsonValue]:
        """Yield every record across pages, one at a time."""
        return iter_items(self.send, spec, strategy, max_pages=max_pages)

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", path, params=params, headers=headers)

    async def head(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("HEAD", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST", path, params=params, headers=headers, json=json, content=content
        )

    async def put(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return await self.request(
            "PUT", path, params=params, headers=headers, json=json, content=content
        )

    async def patch(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return await self.request(
            "PATCH", path, params=params, headers=headers, json=json, content=content
        )

    async def delete(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("DELETE", path, params=params, headers=headers)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"


class Client:
    """Blocking client for one API. Must not be used from inside a running event loop.

    Takes the same options as ``AsyncClient``.
    """

    def __init__(
        self,
        api: ResolvedApi,
        *,
        middleware: Sequence[Middleware] = (),
        auth: AuthHandler | None = None,
        classifier: Classifier | None = None,
        state: StateStore | None = None,
        rate_limiters: RateLimiters | None = None,
        clock: Clock | None = None,
        rng: random.Random | None = None,
        hooks: Hooks | None = None,
        log_bodies: bool = False,
        telemetry: bool = False,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._inner = AsyncClient(
            api,
            middleware=middleware,
            auth=auth,
            classifier=classifier,
            state=state,
            rate_limiters=rate_limiters,
            clock=clock,
            rng=rng,
            hooks=hooks,
            log_bodies=log_bodies,
            telemetry=telemetry,
        )

    @property
    def name(self) -> str:
        return self._inner.name

    def request(
        self,
        method: HTTPMethod,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return self._run(
            self._inner.request(
                method, path, params=params, headers=headers, json=json, content=content
            )
        )

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return self._run(self._inner.get(path, params=params, headers=headers))

    def post(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return self._run(
            self._inner.post(path, params=params, headers=headers, json=json, content=content)
        )

    def put(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return self._run(
            self._inner.put(path, params=params, headers=headers, json=json, content=content)
        )

    def patch(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return self._run(
            self._inner.patch(path, params=params, headers=headers, json=json, content=content)
        )

    def delete(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return self._run(self._inner.delete(path, params=params, headers=headers))

    def head(
        self,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return self._run(self._inner.head(path, params=params, headers=headers))

    def close(self) -> None:
        self._run(self._inner.aclose())
        self._loop.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _run(self, coro: Awaitable[T]) -> T:
        return self._loop.run_until_complete(coro)
