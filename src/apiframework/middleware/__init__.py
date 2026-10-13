"""Request middleware. Concrete layers (logging, retry, auth, ratelimit) land here."""

from __future__ import annotations

from apiframework.middleware.base import CallNext, Middleware

__all__ = ["CallNext", "Middleware"]
