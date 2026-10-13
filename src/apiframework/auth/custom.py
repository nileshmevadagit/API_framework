"""Escape hatch: any function that takes a request and returns a signed or changed copy.

Use it for request signing (HMAC, SigV4) or anything the built-in schemes do not cover.
Python only; a YAML config cannot express a callable.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from apiframework.request import RequestSpec

    AuthFunction = Callable[[RequestSpec], RequestSpec | Awaitable[RequestSpec]]


class CustomAuth:
    def __init__(self, function: AuthFunction) -> None:
        self._function = function

    async def apply(self, req: RequestSpec) -> RequestSpec:
        result = self._function(req)
        if inspect.isawaitable(result):
            return await result
        return result

    async def on_unauthorized(self) -> bool:
        return False
