"""Each pagination strategy: the next request it builds, and when it stops."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apiframework.errors import PaginationError
from apiframework.pagination import (
    CursorPagination,
    LinkHeaderPagination,
    NextUrlPagination,
    OffsetPagination,
    PagePagination,
)
from apiframework.pagination.base import json_path
from apiframework.request import RequestSpec

BASE = "https://api.test/v1"


def _req(url: str = f"{BASE}/items", **kwargs: Any) -> RequestSpec:
    return RequestSpec(method="GET", url=url, **kwargs)


def _json(body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers)


@pytest.mark.parametrize(
    ("data", "path", "expected"),
    [
        ({"a": {"b": 1}}, "a.b", 1),
        ({"items": [{"id": 9}]}, "items.0.id", 9),
        ({"a": None}, "a", None),
        ({"a": 1}, "a.b", None),
        ([1, 2], "5", None),
    ],
)
def test_json_path(data: Any, path: str, expected: Any) -> None:
    assert json_path(data, path) == expected


class TestOffset:
    def test_advances_by_records_read(self) -> None:
        strategy = OffsetPagination(limit=3)
        page = _json([1, 2, 3])
        nxt = strategy.next_request(_req(params={"offset": "0", "limit": "3"}), page)
        assert nxt is not None
        assert dict(nxt.params) == {"offset": "3", "limit": "3"}

    def test_stops_on_empty_page(self) -> None:
        assert OffsetPagination(limit=3).next_request(_req(), _json([])) is None

    def test_reads_items_from_a_key(self) -> None:
        strategy = OffsetPagination(limit=2, items_path="data")
        assert strategy.items(_json({"data": [1, 2]})) == [1, 2]


class TestPage:
    def test_increments_page_number(self) -> None:
        nxt = PagePagination().next_request(_req(params={"page": "2"}), _json([{"id": 1}]))
        assert nxt is not None
        assert dict(nxt.params) == {"page": "3"}

    def test_starts_from_configured_page_when_absent(self) -> None:
        nxt = PagePagination(start=0).next_request(_req(), _json([{"id": 1}]))
        assert nxt is not None
        assert dict(nxt.params) == {"page": "1"}

    def test_stops_on_empty_page(self) -> None:
        assert PagePagination().next_request(_req(), _json([])) is None


class TestCursor:
    def test_sends_cursor_back_as_a_parameter(self) -> None:
        strategy = CursorPagination(cursor_path="meta.next", items_path="data")
        page = _json({"data": [1], "meta": {"next": "abc"}})
        nxt = strategy.next_request(_req(params={"cursor": "old"}), page)
        assert nxt is not None
        assert dict(nxt.params) == {"cursor": "abc"}

    @pytest.mark.parametrize("cursor", [None, ""])
    def test_stops_when_cursor_is_missing_or_empty(self, cursor: Any) -> None:
        strategy = CursorPagination(cursor_path="meta.next", items_path="data")
        assert strategy.next_request(_req(), _json({"data": [1], "meta": {"next": cursor}})) is None

    def test_cursor_zero_is_a_real_cursor(self) -> None:
        strategy = CursorPagination(cursor_path="next", items_path="data")
        nxt = strategy.next_request(_req(), _json({"data": [1], "next": 0}))
        assert nxt is not None
        assert dict(nxt.params) == {"cursor": "0"}


class TestLinkHeader:
    def test_follows_rel_next_and_drops_old_params(self) -> None:
        link = f'<{BASE}/items?page=2>; rel="next", <{BASE}/items?page=9>; rel="last"'
        nxt = LinkHeaderPagination().next_request(
            _req(params={"page": "1"}), _json([1], {"Link": link})
        )
        assert nxt is not None
        assert nxt.url == f"{BASE}/items?page=2"
        assert nxt.params == ()

    def test_resolves_relative_links_against_the_request(self) -> None:
        nxt = LinkHeaderPagination().next_request(
            _req(), _json([1], {"Link": '</items?page=2>; rel="next"'})
        )
        assert nxt is not None
        assert nxt.url == "https://api.test/items?page=2"

    def test_stops_without_a_next_link(self) -> None:
        link = f'<{BASE}/items?page=9>; rel="last"'
        assert LinkHeaderPagination().next_request(_req(), _json([1], {"Link": link})) is None


class TestNextUrl:
    def test_follows_absolute_next_url(self) -> None:
        body = {"data": [1], "links": {"next": f"{BASE}/items?after=5"}}
        nxt = NextUrlPagination(url_path="links.next", items_path="data").next_request(
            _req(), _json(body)
        )
        assert nxt is not None
        assert nxt.url == f"{BASE}/items?after=5"

    def test_resolves_relative_next_url(self) -> None:
        body = {"data": [1], "links": {"next": "/items?after=5"}}
        nxt = NextUrlPagination(url_path="links.next", items_path="data").next_request(
            _req(), _json(body)
        )
        assert nxt is not None
        assert nxt.url == "https://api.test/items?after=5"

    def test_stops_when_next_is_null(self) -> None:
        strategy = NextUrlPagination(url_path="links.next", items_path="data")
        assert strategy.next_request(_req(), _json({"data": [1], "links": {"next": None}})) is None


def test_non_list_items_are_a_pagination_error() -> None:
    with pytest.raises(PaginationError, match="expected a list"):
        PagePagination(items_path="data").items(_json({"data": {"not": "a list"}}))


def test_non_json_page_is_a_pagination_error() -> None:
    with pytest.raises(PaginationError, match="not JSON"):
        PagePagination().items(httpx.Response(200, text="<html>"))
