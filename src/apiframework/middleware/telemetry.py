"""OpenTelemetry span per logical request. Needs the ``otel`` extra.

The tracer is any object with ``start_as_current_span``, so tests can inject a fake. The
span name uses the URL template, and the attribute names follow OpenTelemetry's HTTP
conventions (``http.request.method``, ``http.route``, ``http.response.status_code``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from apiframework.middleware.retry import ATTEMPTS_KEY

if TYPE_CHECKING:
    import httpx

    from apiframework.middleware.base import CallNext
    from apiframework.request import RequestSpec


class Span(Protocol):
    def set_attribute(self, key: str, value: Any) -> None: ...

    def record_exception(self, exception: BaseException) -> None: ...


class Tracer(Protocol):
    def start_as_current_span(self, name: str) -> Any: ...


class TelemetryMiddleware:
    def __init__(self, *, api: str, tracer: Tracer) -> None:
        self._api = api
        self._tracer = tracer

    async def __call__(self, req: RequestSpec, call_next: CallNext) -> httpx.Response:
        with self._tracer.start_as_current_span(f"{req.method} {req.url_template}") as span:
            span.set_attribute("http.request.method", req.method)
            span.set_attribute("http.route", req.url_template)
            span.set_attribute("apiframework.api", self._api)
            try:
                response = await call_next(req)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.record_exception(exc)
                raise
            span.set_attribute("http.response.status_code", response.status_code)
            attempts = response.extensions.get(ATTEMPTS_KEY)
            if isinstance(attempts, int):
                span.set_attribute("apiframework.attempts", attempts)
            return response


def get_tracer() -> Tracer:
    """Return the OpenTelemetry tracer for apiframework. Imported lazily: optional extra."""
    try:
        import opentelemetry.trace as otel_trace
    except ImportError as exc:
        raise ImportError("OpenTelemetry support needs it: pip install apiframework[otel]") from exc
    tracer: Tracer = otel_trace.get_tracer("apiframework")
    return tracer
