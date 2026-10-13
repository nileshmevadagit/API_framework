"""The five built-in strategies: offset, page number, cursor, Link header and next URL.

Each one stops on an empty page or a missing next pointer. Offset and page strategies
stop on an empty page rather than a short one, because servers may cap page sizes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.pagination.base import (
    json_path,
    page_items,
    param_value,
    resolve_url,
    with_params,
)

if TYPE_CHECKING:
    import httpx
    from pydantic import JsonValue

    from apiframework.request import RequestSpec


class OffsetPagination:
    """``?offset=N&limit=M``: the next offset is the last one plus the records just read."""

    def __init__(
        self,
        *,
        limit: int,
        limit_param: str = "limit",
        offset_param: str = "offset",
        items_path: str = "",
    ) -> None:
        self._limit = limit
        self._limit_param = limit_param
        self._offset_param = offset_param
        self._items_path = items_path

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        items = self.items(response)
        if not items:
            return None
        offset = int(param_value(current, self._offset_param) or 0)
        return with_params(
            current,
            **{
                self._offset_param: str(offset + len(items)),
                self._limit_param: str(self._limit),
            },
        )

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return page_items(response, self._items_path)


class PagePagination:
    """``?page=N``: counts pages from ``start``."""

    def __init__(self, *, page_param: str = "page", start: int = 1, items_path: str = "") -> None:
        self._page_param = page_param
        self._start = start
        self._items_path = items_path

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        if not self.items(response):
            return None
        page = int(param_value(current, self._page_param) or self._start)
        return with_params(current, **{self._page_param: str(page + 1)})

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return page_items(response, self._items_path)


class CursorPagination:
    """An opaque cursor in the body, such as ``meta.next_cursor``, sent back as a parameter."""

    def __init__(
        self,
        *,
        cursor_path: str,
        cursor_param: str = "cursor",
        items_path: str = "",
    ) -> None:
        self._cursor_path = cursor_path
        self._cursor_param = cursor_param
        self._items_path = items_path

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        cursor = json_path(_body(response), self._cursor_path)
        if cursor is None or cursor == "" or cursor is False:
            return None
        return with_params(current, **{self._cursor_param: str(cursor)})

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return page_items(response, self._items_path)


class LinkHeaderPagination:
    """RFC 8288 ``Link: <url>; rel="next"``, as used by GitHub and many others."""

    def __init__(self, *, rel: str = "next") -> None:
        self._rel = rel

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        link = response.links.get(self._rel)
        if link is None or not link.get("url"):
            return None
        # The URL carries its own query string, so drop params rather than merge them.
        return current.clone(url=resolve_url(current, link["url"]), params=())

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return page_items(response, "")


class NextUrlPagination:
    """A next URL inside the body, such as ``links.next``. Relative URLs are resolved."""

    def __init__(self, *, url_path: str, items_path: str = "") -> None:
        self._url_path = url_path
        self._items_path = items_path

    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        target = json_path(_body(response), self._url_path)
        if not isinstance(target, str) or not target:
            return None
        return current.clone(url=resolve_url(current, target), params=())

    def items(self, response: httpx.Response) -> list[JsonValue]:
        return page_items(response, self._items_path)


def _body(response: httpx.Response) -> JsonValue:
    try:
        body: JsonValue = response.json()
    except ValueError:
        return None
    return body
