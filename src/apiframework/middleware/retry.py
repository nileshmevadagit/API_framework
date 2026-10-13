"""Retry middleware. Sits outside auth and rate limits, so every attempt is fresh and counted.

Retries only when a retry can help: a retryable verdict, a connection error or a read
timeout, and a method that is safe to repeat. Non-idempotent methods (POST, PATCH) retry
only with ``retry_non_idempotent`` or an ``Idempotency-Key`` header.

The attempt count is written to ``response.extensions[ATTEMPTS_KEY]`` on success, and onto
the error otherwise, so the access log outside this layer can report it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from apiframework.errors import HTTPStatusError, ResponseRejected, RetryExhausted
from apiframework.hooks import RetryEvent
from apiframework.middleware.backoff import backoff_delay, parse_retry_after
from apiframework.middleware.classify import StatusClassifier, Verdict

if TYPE_CHECKING:
    import random

    from apiframework.clock import Clock
    from apiframework.config import RetryConfig
    from apiframework.hooks import Hooks
    from apiframework.middleware.base import CallNext
    from apiframework.middleware.classify import Classifier
    from apiframework.request import RequestSpec

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})
CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
ATTEMPTS_KEY = "apiframework.attempts"


class RetryMiddleware:
    def __init__(
        self,
        config: RetryConfig,
        *,
        clock: Clock,
        rng: random.Random,
        classifier: Classifier | None = None,
        api: str = "",
        hooks: Hooks | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._rng = rng
        self._classifier: Classifier = classifier if classifier is not None else StatusClassifier()
        self._api = api
        self._hooks = hooks

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        may_retry = self._may_retry(req)
        attempt = 1
        while True:
            error: Exception | None = None
            response: httpx.Response | None = None
            try:
                response = await call_next(req)
            except CONNECTION_ERRORS as exc:
                error = exc
                verdict = Verdict.RETRYABLE
            else:
                verdict = self._classifier.classify(response)

            if verdict is Verdict.OK:
                assert response is not None  # OK is only reached with a response
                response.extensions[ATTEMPTS_KEY] = attempt
                return response

            if verdict is Verdict.FAILURE:
                assert response is not None
                raise _failure(response, attempt)

            # Retryable, but only if the method allows it and budget remains.
            if error is not None:
                last: Exception = error
            else:
                assert response is not None  # a non-error verdict always has a response
                last = _failure(response, attempt)
            if not may_retry or attempt >= self._config.max_attempts:
                raise RetryExhausted(attempt, last_error=last)

            delay = self._retry_after(response)
            if delay is None:
                delay = backoff_delay(attempt, self._config, self._rng)
            if self._hooks is not None:
                self._hooks.emit_retry(
                    RetryEvent(
                        api=self._api,
                        method=req.method,
                        url_template=req.url_template,
                        attempt=attempt,
                        delay_s=delay,
                        reason="connection" if error is not None else "status",
                    )
                )
            await self._clock.sleep(delay)
            attempt += 1

    def _may_retry(self, req: RequestSpec) -> bool:
        if req.method in IDEMPOTENT_METHODS or self._config.retry_non_idempotent:
            return True
        return any(name.lower() == "idempotency-key" for name, _ in req.headers)

    def _retry_after(self, response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        header = response.headers.get("Retry-After")
        if header is None:
            return None
        return parse_retry_after(header, self._clock.now())


def _failure(response: httpx.Response, attempts: int) -> Exception:
    if response.status_code >= 400:
        return HTTPStatusError(response, attempts=attempts)
    return ResponseRejected(
        response, reason="classifier rejected a successful status", attempts=attempts
    )
