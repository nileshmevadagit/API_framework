from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from apiframework.errors import (
    ApiError,
    AuthError,
    ConfigError,
    HTTPStatusError,
    QuotaExhausted,
    RetryExhausted,
)


@pytest.mark.parametrize(
    "exc_type",
    [HTTPStatusError, RetryExhausted, QuotaExhausted, AuthError, ConfigError],
)
def test_every_public_error_is_an_api_error(exc_type: type[ApiError]) -> None:
    assert issubclass(exc_type, ApiError)


def test_api_error_is_an_exception() -> None:
    assert issubclass(ApiError, Exception)


def test_http_status_error_carries_response_and_status() -> None:
    response = httpx.Response(503)
    err = HTTPStatusError(response)
    assert err.response is response
    assert err.status_code == 503
    assert str(err) == "HTTP 503"


def test_retry_exhausted_records_attempts_and_last_error() -> None:
    cause = ConnectionError("boom")
    err = RetryExhausted(attempts=4, last_error=cause)
    assert err.attempts == 4
    assert err.last_error is cause
    assert "4 attempt" in str(err)


def test_retry_exhausted_last_error_is_optional() -> None:
    assert RetryExhausted(attempts=1).last_error is None


def test_quota_exhausted_carries_reset_time_as_aware_datetime() -> None:
    reset = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    err = QuotaExhausted("github:hour", reset)
    assert err.key == "github:hour"
    assert err.reset_at == reset
    assert err.reset_at.tzinfo is not None
    assert "2026-10-12T18:00:00+00:00" in str(err)
