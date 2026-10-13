"""The iterators own pagination state: they stop, cap pages, and detect loops."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apiframework.errors import PaginationError
from apiframework.pagination import PagePagination, iter_items, iter_pages
from apiframework.request import RequestSpec

if TYPE_CHECKING:
    from pydantic import JsonValue

    from apiframework.pagination.base import PaginationStrategy

BASE = "https://api.test/v1"


def _pages(data: list[list[JsonValue]]) -> tuple[Any, list[RequestSpec]]:
    """A fake send(): serves ``data`` as pages 1, 2, ... and records what it was asked."""
    sent: list[RequestSpec] = []

    async def send(req: RequestSpec) -> httpx.Response:
        sent.append(req)
        page = int(dict(req.params).get("page", "1"))
        body = data[page - 1] if page <= len(data) else []
        return httpx.Response(200, json=body)

    return send, sent


def _first() -> RequestSpec:
    return RequestSpec(method="GET", url=f"{BASE}/items", params={"page": "1"})


async def test_items_are_collected_across_pages() -> None:
    send, sent = _pages([[1, 2], [3], []])
    items = [item async for item in iter_items(send, _first(), PagePagination())]
    assert items == [1, 2, 3]
    assert len(sent) == 3  # the empty third page is what tells us to stop


async def test_max_pages_caps_the_walk() -> None:
    send, sent = _pages([[1], [2], [3], [4]])
    items = [item async for item in iter_items(send, _first(), PagePagination(), max_pages=2)]
    assert items == [1, 2]
    assert len(sent) == 2


async def test_pages_are_yielded_as_responses() -> None:
    send, _ = _pages([[1], []])
    pages = [page async for page in iter_pages(send, _first(), PagePagination())]
    assert [p.status_code for p in pages] == [200, 200]


class _PointsBack:
    """Always answers with the request it was given, so the walk would loop forever."""

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        return current

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return [1]


async def test_a_repeated_request_is_a_pagination_error() -> None:
    send, sent = _pages([])
    strategy: PaginationStrategy = _PointsBack()
    with pytest.raises(PaginationError, match="repeats"):
        async for _ in iter_items(send, _first(), strategy):
            pass
    assert len(sent) == 1  # the repeat is refused before it is sent


async def test_empty_first_page_yields_nothing() -> None:
    send, _ = _pages([])
    assert [item async for item in iter_items(send, _first(), PagePagination())] == []
