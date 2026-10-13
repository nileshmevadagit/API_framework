from __future__ import annotations

import httpx
import pytest

from apiframework.middleware.classify import StatusClassifier, Verdict


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        (200, Verdict.OK),
        (204, Verdict.OK),
        (302, Verdict.OK),
        (408, Verdict.RETRYABLE),
        (425, Verdict.RETRYABLE),
        (429, Verdict.RETRYABLE),
        (503, Verdict.RETRYABLE),
        (400, Verdict.FAILURE),
        (401, Verdict.FAILURE),
        (404, Verdict.FAILURE),
        (501, Verdict.FAILURE),
    ],
)
def test_status_classifier(status: int, verdict: Verdict) -> None:
    assert StatusClassifier().classify(httpx.Response(status)) is verdict
