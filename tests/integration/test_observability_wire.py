"""Hooks, access log and telemetry over real HTTP against httpbin. Needs docker-compose httpbin."""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import RetryExhausted
from apiframework.hooks import Hooks

pytestmark = pytest.mark.integration

HTTPBIN = os.environ.get("HTTPBIN_URL", "http://localhost:8080")


async def test_hooks_report_retries_against_a_real_503(caplog: pytest.LogCaptureFixture) -> None:
    retries: list[Any] = []
    responses: list[Any] = []
    hooks = Hooks(on_retry=retries.append, on_response=responses.append)
    cfg = parse_config(
        {
            "defaults": {"retry": {"max_attempts": 3, "backoff_base": 0.01, "max_backoff": 0.02}},
            "apis": {"echo": {"base_url": HTTPBIN}},
        },
        env={},
    )
    caplog.set_level(logging.INFO, logger="apiframework.request")
    async with AsyncClient(cfg.api("echo"), hooks=hooks) as client:
        with pytest.raises(RetryExhausted):
            await client.get("/status/503")

    assert [r.attempt for r in retries] == [1, 2]
    (final,) = responses
    assert (final.status, final.attempts, final.error) == (503, 3, "RetryExhausted")
    assert any(
        r.levelno == logging.WARNING for r in caplog.records if r.name == "apiframework.request"
    )


async def test_telemetry_flag_works_over_the_wire() -> None:
    cfg = parse_config({"apis": {"echo": {"base_url": HTTPBIN}}}, env={})
    async with AsyncClient(cfg.api("echo"), telemetry=True) as client:
        response = await client.get("/get", params={"a": 1})
    assert response.status_code == 200
