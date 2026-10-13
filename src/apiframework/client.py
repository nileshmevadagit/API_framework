"""Clients. ``AsyncClient`` holds the logic; ``Client`` is a thin sync wrapper over it.

One client talks to one API. Each client owns its connection pool, so two clients in
one process never share state. Call ``aclose()`` / ``close()`` when you are done, or
use the client as a context manager.

Responses are returned as received. Status classification and retries arrive with the
retry middleware in milestone 3.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeVar

from apiframework.middleware.chain import build_chain
from apiframework.request import RequestSpec
from apiframework.transport import HTTPTransport

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping, Sequence
    from types import TracebackType

    import httpx
    from pydantic import JsonValue
    from typing_extensions import Self

    from apiframework.config import ResolvedApi
    from apiframework.middleware.base import Middleware
    from apiframework.request import HTTPMethod

ParamValue = str | int | float | bool
T = TypeVar("T")


def _param_text(value: ParamValue) -> str:
    # Query strings use lowercase booleans, not Python's True/False.
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class AsyncClient:
    """Async client for one API. Use ``await client.get(...)`` and friends."""

    def __init__(self, api: ResolvedApi, *, middleware: Sequence[Middleware] = ()) -> None:
        self.name = api.name
        self._base_url = api.base_url.rstrip("/")
        self._transport = HTTPTransport(api)
        self._chain = build_chain(middleware, self._transport.send)

    async def send(self, spec: RequestSpec) -> httpx.Response:
        """Send a prepared request through the middleware chain."""
        return await self._chain(spec)

    async def request(
        self,
        method: HTTPMethod,
        path: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Build a request for ``path`` (relative to the API's base URL) and send it.

        Pass ``json`` or ``content``, not both.
        """
        if json is not None and content is not None:
            raise ValueError("pass json or content, not both")
        spec = RequestSpec(
            method=method,
            url=self._url(path),
            url_template=path,
            params=tuple((key, _param_text(value)) for key, value in (params or {}).items()),
            headers=tuple((key, value) for key, value in (headers or {}).items()),
            json_body=json,
            content=content,
        )
        return await self.send(spec)

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
    """Blocking client for one API. Must not be used from inside a running event loop."""

    def __init__(self, api: ResolvedApi, *, middleware: Sequence[Middleware] = ()) -> None:
        self._loop = asyncio.new_event_loop()
        self._inner = AsyncClient(api, middleware=middleware)

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
