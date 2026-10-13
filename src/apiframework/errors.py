"""Error hierarchy. Everything raised to users subclasses ApiError."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    import httpx


class ApiError(Exception):
    """Base class for every error apiframework raises to its users."""


class HTTPStatusError(ApiError):
    """The server answered with a status we do not accept. Carries the response."""

    def __init__(self, response: httpx.Response, *, attempts: int = 1) -> None:
        self.response = response
        self.status_code = response.status_code
        self.attempts = attempts
        super().__init__(f"HTTP {response.status_code}")


class RetryExhausted(ApiError):
    """A retryable failure kept happening until the attempt budget ran out."""

    def __init__(self, attempts: int, last_error: BaseException | None = None) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"gave up after {attempts} attempt(s)")


class QuotaExhausted(ApiError):
    """A quota window is used up. ``reset_at`` is when the window reopens (UTC)."""

    def __init__(self, key: str, reset_at: datetime) -> None:
        self.key = key
        self.reset_at = reset_at
        super().__init__(f"quota {key!r} exhausted until {reset_at.isoformat()}")


class AuthError(ApiError):
    """Credentials are missing, rejected, or could not be refreshed."""


class ConfigError(ApiError):
    """Configuration is invalid or refers to something that does not exist."""


class ResponseRejected(ApiError):
    """The response classifier rejected a response whose status was not an HTTP error.

    Used for APIs that return 200 with an error in the body (GraphQL, JSON-RPC).
    """

    def __init__(self, response: httpx.Response, reason: str, *, attempts: int = 1) -> None:
        self.response = response
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"response rejected: {reason}")


class PaginationError(ApiError):
    """Pagination cannot continue safely, for example because the next URL repeats."""
