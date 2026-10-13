"""Access log: one record per logical request, written outside retry.

Logs the URL template, never the filled-in URL, so IDs stay out of the logs. Headers are
logged only at DEBUG and only after redaction. Bodies are logged only at DEBUG and only when
the client was built with ``log_bodies=True``, since bodies can contain anything.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from apiframework.errors import HTTPStatusError, ResponseRejected, RetryExhausted
from apiframework.hooks import RequestEvent, ResponseEvent
from apiframework.middleware.retry import ATTEMPTS_KEY
from apiframework.secrets import redact_headers

if TYPE_CHECKING:
    import httpx

    from apiframework.hooks import Hooks
    from apiframework.middleware.base import CallNext
    from apiframework.request import RequestSpec

logger = logging.getLogger("apiframework.request")
BODY_PREVIEW_CHARS = 2000


class AccessLogMiddleware:
    def __init__(self, *, api: str, hooks: Hooks | None = None, log_bodies: bool = False) -> None:
        self._api = api
        self._hooks = hooks
        self._log_bodies = log_bodies

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        if self._hooks is not None:
            self._hooks.emit_request(RequestEvent(self._api, req.method, req.url_template))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "request headers",
                extra=self._fields(req, headers=redact_headers(req.headers)),
            )
        started = time.monotonic()
        try:
            response = await call_next(req)
        except Exception as exc:
            latency = time.monotonic() - started
            status = _status_of(exc)
            attempts = _attempts_of(exc)
            self._record(req, status, latency, attempts, error=type(exc).__name__)
            logger.warning(
                "%s %s failed: %s",
                req.method,
                req.url_template,
                type(exc).__name__,
                extra=self._fields(req, status=status, attempts=attempts, latency=latency),
            )
            raise

        latency = time.monotonic() - started
        attempts = response.extensions.get(ATTEMPTS_KEY)
        self._record(req, response.status_code, latency, attempts, error=None)
        logger.info(
            "%s %s -> %d",
            req.method,
            req.url_template,
            response.status_code,
            extra=self._fields(
                req, status=response.status_code, attempts=attempts, latency=latency
            ),
        )
        if self._log_bodies and logger.isEnabledFor(logging.DEBUG):
            self._log_body_preview(req, response)
        return response

    def _record(
        self,
        req: RequestSpec,
        status: int | None,
        latency: float,
        attempts: int | None,
        *,
        error: str | None,
    ) -> None:
        if self._hooks is None:
            return
        self._hooks.emit_response(
            ResponseEvent(
                api=self._api,
                method=req.method,
                url_template=req.url_template,
                status=status,
                latency_s=latency,
                attempts=attempts,
                error=error,
            )
        )

    def _fields(self, req: RequestSpec, **extra: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "api": self._api,
            "method": req.method,
            "url_template": req.url_template,
        }
        if "latency" in extra:
            fields["latency_ms"] = round(extra.pop("latency") * 1000, 1)
        fields.update(extra)
        return fields

    def _log_body_preview(self, req: RequestSpec, response: httpx.Response) -> None:
        sent = req.json_body if req.json_body is not None else req.content
        logger.debug("request body: %s", str(sent)[:BODY_PREVIEW_CHARS], extra=self._fields(req))
        logger.debug(
            "response body: %s",
            response.text[:BODY_PREVIEW_CHARS],
            extra=self._fields(req, status=response.status_code),
        )


def _status_of(exc: BaseException) -> int | None:
    if isinstance(exc, HTTPStatusError):
        return exc.status_code
    if isinstance(exc, ResponseRejected):
        return exc.response.status_code
    if isinstance(exc, RetryExhausted) and isinstance(exc.last_error, HTTPStatusError):
        return exc.last_error.status_code
    return None


def _attempts_of(exc: BaseException) -> int | None:
    if isinstance(exc, (HTTPStatusError, ResponseRejected, RetryExhausted)):
        return exc.attempts
    return None
