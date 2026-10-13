"""Access log, hooks, JSON logs and telemetry, with HTTP mocked by respx and a fake clock."""

from __future__ import annotations

import io
import json
import logging
import random
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import HTTPStatusError
from apiframework.hooks import Hooks
from apiframework.logging_json import JsonFormatter
from apiframework.middleware.telemetry import get_tracer

if TYPE_CHECKING:
    import respx

    from fakes import FakeClock

BASE = "https://api.test/v1"
SECRET = "Bearer sekrit-token-123"


def _client(clock: FakeClock, *, hooks: Hooks | None = None, **kwargs: Any) -> AsyncClient:
    cfg = parse_config(
        {
            "defaults": {"retry": {"max_attempts": 3, "backoff_base": 0.5}},
            "apis": {"demo": {"base_url": BASE, "headers": {"X-Trace": "t"}}},
        },
        env={},
    )
    return AsyncClient(cfg.api("demo"), clock=clock, rng=random.Random(1), hooks=hooks, **kwargs)


def _records(caplog: pytest.LogCaptureFixture, logger: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == logger]


async def test_access_log_has_template_status_and_attempts(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get(f"{BASE}/users/42").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"id": 42})]
    )
    caplog.set_level(logging.INFO, logger="apiframework.request")
    async with _client(clock) as client:
        await client.get("/users/42")

    (record,) = _records(caplog, "apiframework.request")
    assert record.levelno == logging.INFO
    assert record.url_template == "/users/42"  # no url_template given: the path is the template
    assert record.status == 200
    assert record.attempts == 2
    assert record.api == "demo"
    assert record.latency_ms >= 0


async def test_url_template_keeps_ids_out_of_the_logs(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get(f"{BASE}/users/98765").mock(return_value=httpx.Response(200))
    caplog.set_level(logging.DEBUG, logger="apiframework.request")
    async with _client(clock) as client:
        await client.request("GET", "/users/98765", url_template="/users/{id}")

    texts = [r.getMessage() + repr(r.__dict__.get("url_template")) for r in caplog.records]
    assert all("98765" not in text for text in texts)
    assert any("/users/{id}" in text for text in texts)


async def test_failed_call_is_logged_as_a_warning(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get(f"{BASE}/missing").mock(return_value=httpx.Response(404))
    caplog.set_level(logging.INFO, logger="apiframework.request")
    async with _client(clock) as client:
        with pytest.raises(HTTPStatusError, match="HTTP 404"):
            await client.get("/missing")

    (record,) = _records(caplog, "apiframework.request")
    assert record.levelno == logging.WARNING
    assert record.status == 404
    assert record.attempts == 1


async def test_hooks_see_request_retry_response_and_rate_limit_events(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    events: dict[str, list[Any]] = {"request": [], "retry": [], "response": []}
    hooks = Hooks(
        on_request=events["request"].append,
        on_retry=events["retry"].append,
        on_response=events["response"].append,
    )
    respx_mock.get(f"{BASE}/x").mock(side_effect=[httpx.Response(503), httpx.Response(200)])
    async with _client(clock, hooks=hooks) as client:
        await client.get("/x")

    assert [e.url_template for e in events["request"]] == ["/x"]
    (retry,) = events["retry"]
    assert (retry.attempt, retry.reason, retry.api) == (1, "status", "demo")
    assert retry.delay_s == pytest.approx(clock.slept[0])
    (response,) = events["response"]
    assert (response.status, response.attempts, response.error) == (200, 2, None)


async def test_rate_limit_wait_and_refusal_reach_hooks(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    from apiframework.errors import QuotaExhausted
    from apiframework.state import MemoryStateStore

    limited: list[Any] = []
    hooks = Hooks(on_rate_limited=limited.append)
    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    cfg = parse_config(
        {
            "apis": {
                "demo": {
                    "base_url": BASE,
                    "rate_limits": [
                        {"window": "second", "limit": 1},
                    ],
                }
            }
        },
        env={},
    )
    async with AsyncClient(
        cfg.api("demo"), clock=clock, state=MemoryStateStore(clock), hooks=hooks
    ) as client:
        await client.get("/x")
        await client.get("/x")  # the bucket is empty, so this waits
    assert len(limited) == 1
    assert limited[0].waited_s == pytest.approx(1.0)
    assert limited[0].exhausted is False

    capped = parse_config(
        {"apis": {"demo": {"base_url": BASE, "rate_limits": [{"window": "hour", "limit": 1}]}}},
        env={},
    )
    refused: list[Any] = []
    async with AsyncClient(
        capped.api("demo"),
        clock=clock,
        state=MemoryStateStore(clock),
        hooks=Hooks(on_rate_limited=refused.append),
    ) as client:
        await client.get("/x")
        with pytest.raises(QuotaExhausted):
            await client.get("/x")
    assert refused[-1].exhausted is True


async def test_a_failing_hook_does_not_fail_the_request(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(event: Any) -> None:
        raise RuntimeError("metrics backend down")

    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"ok": True}))
    caplog.set_level(logging.WARNING, logger="apiframework.hooks")
    async with _client(clock, hooks=Hooks(on_request=broken, on_response=broken)) as client:
        response = await client.get("/x")
    assert response.json() == {"ok": True}
    assert any("hook on_request raised" in r.getMessage() for r in caplog.records)


async def test_headers_are_redacted_in_debug_logs(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    caplog.set_level(logging.DEBUG, logger="apiframework.request")
    async with _client(clock) as client:
        await client.get("/x", headers={"Authorization": SECRET, "X-Api-Key": "k-999"})

    header_records = [r for r in caplog.records if r.getMessage() == "request headers"]
    assert header_records, "DEBUG should log the (redacted) headers"
    logged = json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert "sekrit-token-123" not in logged
    assert "k-999" not in logged
    assert "[redacted]" in logged


async def test_bodies_are_not_logged_unless_asked(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.post(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"echo": "BODY-VALUE"}))
    caplog.set_level(logging.DEBUG, logger="apiframework.request")
    async with _client(clock) as client:
        await client.post("/x", json={"secret": "BODY-VALUE"})
    assert "BODY-VALUE" not in caplog.text


async def test_bodies_are_logged_at_debug_when_enabled(
    respx_mock: respx.MockRouter, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.post(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"echo": "BODY-VALUE"}))
    caplog.set_level(logging.DEBUG, logger="apiframework.request")
    async with _client(clock, log_bodies=True) as client:
        await client.post("/x", json={"secret": "BODY-VALUE"})
    assert "BODY-VALUE" in caplog.text


async def test_json_formatter_writes_one_object_per_record(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("apiframework.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        async with _client(clock) as client:
            await client.get("/x")
    finally:
        logger.removeHandler(handler)

    (line,) = stream.getvalue().strip().splitlines()
    record = json.loads(line)
    assert record["logger"] == "apiframework.request"
    assert record["url_template"] == "/x"
    assert record["status"] == 200
    assert record["level"] == "INFO"
    assert "ts" in record


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.exceptions: list[BaseException] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def record_exception(self, exception: BaseException) -> None:
        self.exceptions.append(exception)


class _FakeTracer:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.spans: list[_FakeSpan] = []

    def start_as_current_span(self, name: str) -> Any:
        import contextlib

        @contextlib.contextmanager
        def manager() -> Any:
            span = _FakeSpan()
            self.names.append(name)
            self.spans.append(span)
            yield span

        return manager()


async def test_telemetry_span_has_template_and_status(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    from apiframework.middleware.telemetry import TelemetryMiddleware

    tracer = _FakeTracer()
    respx_mock.get(f"{BASE}/users/42").mock(return_value=httpx.Response(200))
    async with _client(
        clock, middleware=[TelemetryMiddleware(api="demo", tracer=tracer)]
    ) as client:
        await client.request("GET", "/users/42", url_template="/users/{id}")

    assert tracer.names == ["GET /users/{id}"]
    attrs = tracer.spans[0].attributes
    assert attrs["http.request.method"] == "GET"
    assert attrs["http.route"] == "/users/{id}"
    assert attrs["http.response.status_code"] == 200
    assert "42" not in json.dumps(attrs)


async def test_telemetry_flag_uses_real_otel_api(
    respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    # The API package is installed in dev; with no SDK configured, spans are no-ops.
    respx_mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    async with _client(clock, telemetry=True) as client:
        assert (await client.get("/x")).status_code == 200


def test_telemetry_without_the_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)
    with pytest.raises(ImportError, match=r"apiframework\[otel\]"):
        get_tracer()
