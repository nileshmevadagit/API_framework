"""Endpoint config, paging config and request building. Nothing is sent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.endpoints import build_request, build_strategy
from apiframework.errors import ConfigError
from apiframework.pagination import (
    CursorPagination,
    LinkHeaderPagination,
    NextUrlPagination,
    OffsetPagination,
    PagePagination,
)

if TYPE_CHECKING:
    from apiframework.config import ResolvedApi

BASE = "https://api.test/v1"


def _api(endpoints: dict[str, object]) -> ResolvedApi:
    cfg = parse_config(
        {"apis": {"demo": {"base_url": BASE, "endpoints": endpoints}}}, env={"TOK": "t"}
    )
    return cfg.api("demo")


def test_each_paging_type_maps_to_its_strategy() -> None:
    api = _api(
        {
            "a": {"method": "GET", "path": "/a", "pagination": {"type": "offset", "limit": 5}},
            "b": {"method": "GET", "path": "/b", "pagination": {"type": "page"}},
            "c": {
                "method": "GET",
                "path": "/c",
                "pagination": {"type": "cursor", "cursor_path": "meta.next"},
            },
            "d": {"method": "GET", "path": "/d", "pagination": {"type": "link_header"}},
            "e": {
                "method": "GET",
                "path": "/e",
                "pagination": {"type": "next_url", "url_path": "links.next"},
            },
        }
    )
    endpoints = api.endpoints
    kinds = {
        name: type(build_strategy(endpoint.pagination)) for name, endpoint in endpoints.items()
    }
    assert kinds == {
        "a": OffsetPagination,
        "b": PagePagination,
        "c": CursorPagination,
        "d": LinkHeaderPagination,
        "e": NextUrlPagination,
    }


def test_unknown_paging_type_is_rejected() -> None:
    with pytest.raises(ConfigError):
        _api({"a": {"method": "GET", "path": "/a", "pagination": {"type": "magic"}}})


def test_endpoint_header_with_a_literal_secret_is_rejected() -> None:
    with pytest.raises(ConfigError, match="pasted secret"):
        _api(
            {
                "a": {
                    "method": "GET",
                    "path": "/a",
                    "headers": {"X-Note": "Bearer ghp_0123456789abcdefghij"},
                }
            }
        )


async def test_build_request_merges_params_and_keeps_the_template() -> None:
    api = _api(
        {
            "posts": {
                "method": "GET",
                "path": "/posts/{id}",
                "params": {"_limit": 10, "_page": 1},
                "cost": 3,
            }
        }
    )
    client = AsyncClient(api)
    endpoint = api.endpoints["posts"]
    spec = build_request(client, endpoint, {"_page": 4})
    await client.aclose()
    assert dict(spec.params) == {"_limit": "10", "_page": "4"}
    assert spec.url_template == "/posts/{id}"
    assert spec.cost == 3
    assert spec.method == "GET"


def test_jobs_must_reference_an_existing_api_and_endpoint() -> None:
    with pytest.raises(ConfigError, match="no API named"):
        parse_config({"jobs": {"j": {"api": "missing", "endpoint": "x"}}}, env={})
    with pytest.raises(ConfigError, match="has no endpoint"):
        parse_config(
            {
                "apis": {"demo": {"base_url": BASE}},
                "jobs": {"j": {"api": "demo", "endpoint": "nope"}},
            },
            env={},
        )


def test_observability_section_defaults_off() -> None:
    cfg = parse_config({}, env={})
    assert cfg.observability.log_bodies is False
    assert cfg.observability.telemetry is False
