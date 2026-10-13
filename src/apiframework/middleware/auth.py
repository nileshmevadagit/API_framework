"""Auth middleware: applies the handler on every attempt, and retries once after a 401."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from apiframework.auth.base import AuthHandler
    from apiframework.middleware.base import CallNext
    from apiframework.request import RequestSpec


class AuthMiddleware:
    def __init__(self, handler: AuthHandler) -> None:
        self._handler = handler

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        response = await call_next(await self._handler.apply(req))
        if response.status_code == 401 and await self._handler.on_unauthorized():
            response = await call_next(await self._handler.apply(req))
        return response
