"""Response classifier: decides whether a response is OK, retryable or a failure.

Status alone is not enough. GraphQL and JSON-RPC return 200 with an error in the body,
so applications can supply their own ``Classifier``.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import httpx

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class Verdict(Enum):
    OK = "ok"
    RETRYABLE = "retryable"
    FAILURE = "failure"


class Classifier(Protocol):
    def classify(self, response: httpx.Response) -> Verdict:
        """Say what to do with ``response``. Must not consume the body."""
        ...


class StatusClassifier:
    """Default: the retryable status list above is retryable, other 4xx/5xx fail, rest is OK."""

    def classify(self, response: httpx.Response) -> Verdict:
        if response.status_code in RETRYABLE_STATUSES:
            return Verdict.RETRYABLE
        if response.status_code >= 400:
            return Verdict.FAILURE
        return Verdict.OK
