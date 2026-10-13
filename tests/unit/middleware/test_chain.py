from __future__ import annotations

from typing import Any

import httpx

from apiframework.middleware.chain import build_chain
from apiframework.request import RequestSpec


def _spec() -> RequestSpec:
    return RequestSpec(method="GET", url="https://x.test/a")


def _layer(name: str, log: list[str]) -> Any:
    async def layer(req: RequestSpec, call_next: Any) -> httpx.Response:
        log.append(f"{name}:in")
        response = await call_next(req)
        log.append(f"{name}:out")
        return response

    return layer


async def test_first_middleware_is_outermost() -> None:
    log: list[str] = []

    async def send(req: RequestSpec) -> httpx.Response:
        log.append("send")
        return httpx.Response(200)

    chain = build_chain([_layer("a", log), _layer("b", log)], send)
    await chain(_spec())
    assert log == ["a:in", "b:in", "send", "b:out", "a:out"]


async def test_empty_chain_is_just_the_transport() -> None:
    async def send(req: RequestSpec) -> httpx.Response:
        return httpx.Response(204)

    chain = build_chain([], send)
    assert (await chain(_spec())).status_code == 204


async def test_a_layer_can_short_circuit() -> None:
    reached: list[str] = []

    async def block(req: RequestSpec, call_next: Any) -> httpx.Response:
        return httpx.Response(429)

    async def send(req: RequestSpec) -> httpx.Response:
        reached.append("send")
        return httpx.Response(200)

    chain = build_chain([block], send)
    assert (await chain(_spec())).status_code == 429
    assert reached == []
