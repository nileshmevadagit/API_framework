"""The Middleware contract: a layer can wrap call_next and pass a cloned spec down the chain."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from apiframework.request import RequestSpec

if TYPE_CHECKING:
    from apiframework.middleware import CallNext, Middleware


class AddHeader:
    """Toy layer: adds one header and delegates. Shows the shape real layers follow."""

    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self._value = value

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        headers = {**dict(req.headers), self._name: self._value}
        return await call_next(req.clone(headers=headers))


async def test_middleware_passes_cloned_spec_downstream() -> None:
    seen: list[RequestSpec] = []

    async def transport(req: RequestSpec) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200)

    original = RequestSpec(method="GET", url="https://x.test/a")
    layer: Middleware = AddHeader("X-Trace", "1")
    response = await layer(original, transport)

    assert response.status_code == 200
    assert seen[0].headers == (("X-Trace", "1"),)
    assert original.headers == ()


async def test_middleware_can_be_tested_alone_with_a_fake_next() -> None:
    async def fake_next(req: RequestSpec) -> httpx.Response:
        assert ("X-Trace", "abc") in req.headers
        return httpx.Response(204)

    response = await AddHeader("X-Trace", "abc")(
        RequestSpec(method="DELETE", url="https://x.test/a"), fake_next
    )
    assert response.status_code == 204
