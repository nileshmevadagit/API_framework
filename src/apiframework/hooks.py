"""Hooks: callbacks for metrics and tracing. The library never logs through them.

Each hook receives a small event object. A hook that raises is logged and skipped, so a
broken metrics callback cannot fail a request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("apiframework.hooks")
E = TypeVar("E")


@dataclass(frozen=True)
class RequestEvent:
    api: str
    method: str
    url_template: str


@dataclass(frozen=True)
class ResponseEvent:
    api: str
    method: str
    url_template: str
    status: int | None  # None when the call ended in an error with no response
    latency_s: float
    attempts: int | None  # None when the call failed before the retry layer counted
    error: str | None  # exception class name, when the call raised


@dataclass(frozen=True)
class RetryEvent:
    api: str
    method: str
    url_template: str
    attempt: int  # the attempt that just failed, counting from 1
    delay_s: float
    reason: str  # "status" or "connection"


@dataclass(frozen=True)
class RateLimitEvent:
    api: str
    waited_s: float  # time spent waiting for quota; 0 if it was available at once
    exhausted: bool  # True when the quota was exhausted and the call raised


class Hooks:
    """Optional callbacks. Assign only the ones you need."""

    def __init__(
        self,
        *,
        on_request: Callable[[RequestEvent], None] | None = None,
        on_response: Callable[[ResponseEvent], None] | None = None,
        on_retry: Callable[[RetryEvent], None] | None = None,
        on_rate_limited: Callable[[RateLimitEvent], None] | None = None,
    ) -> None:
        self.on_request = on_request
        self.on_response = on_response
        self.on_retry = on_retry
        self.on_rate_limited = on_rate_limited

    def emit_request(self, event: RequestEvent) -> None:
        _call("on_request", self.on_request, event)

    def emit_response(self, event: ResponseEvent) -> None:
        _call("on_response", self.on_response, event)

    def emit_retry(self, event: RetryEvent) -> None:
        _call("on_retry", self.on_retry, event)

    def emit_rate_limited(self, event: RateLimitEvent) -> None:
        _call("on_rate_limited", self.on_rate_limited, event)


def _call(name: str, hook: Callable[[E], None] | None, event: E) -> None:
    if hook is None:
        return
    try:
        hook(event)
    except Exception:
        logger.warning("hook %s raised; ignoring it", name, exc_info=True)
