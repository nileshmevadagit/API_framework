"""Compose middleware around a transport. The first entry in the list is the outermost layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from apiframework.middleware.base import CallNext, Middleware
    from apiframework.request import RequestSpec


def build_chain(middleware: Sequence[Middleware], send: CallNext) -> CallNext:
    """Wrap ``send`` in ``middleware``, so calling the result runs the whole chain."""
    call = send
    for layer in reversed(middleware):
        call = _bind(layer, call)
    return call


def _bind(layer: Middleware, call_next: CallNext) -> CallNext:
    async def call(req: RequestSpec) -> httpx.Response:
        return await layer(req, call_next)

    return call
