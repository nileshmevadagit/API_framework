"""Pagination. A strategy only maps (request, response) to the next request and the items.

Strategies hold no state. The loop in ``iter_pages`` keeps the current request and the
set of requests already sent, so pagination state lives in the iterator, not the client.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urljoin

import httpx

from apiframework.errors import PaginationError

if TYPE_CHECKING:
    from pydantic import JsonValue

    from apiframework.request import RequestSpec

Send = Callable[["RequestSpec"], Awaitable[httpx.Response]]


class PaginationStrategy(Protocol):
    def next_request(self, current: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        """Return the request for the next page, or None when this was the last page."""
        ...

    def items(self, response: httpx.Response) -> list[JsonValue]:
        """Return the records on this page."""
        ...


def json_path(data: JsonValue, path: str) -> JsonValue | None:
    """Look up a dotted path such as ``meta.next.cursor`` or ``items.0.id``. Missing is None."""
    current: JsonValue = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
        if current is None:
            return None
    return current


def page_items(response: httpx.Response, items_path: str) -> list[JsonValue]:
    """Return the list at ``items_path`` in the JSON body. An empty path means the body itself."""
    try:
        body: JsonValue = response.json()
    except ValueError as exc:
        raise PaginationError("page is not JSON") from exc
    target = json_path(body, items_path) if items_path else body
    if not isinstance(target, list):
        where = items_path or "the top level"
        raise PaginationError(f"expected a list of items at {where}")
    return target


def with_params(current: RequestSpec, **updates: str) -> RequestSpec:
    """Return a copy with query parameters replaced (or added) by ``updates``."""
    kept = tuple((key, val) for key, val in current.params if key not in updates)
    return current.clone(params=(*kept, *updates.items()))


def param_value(current: RequestSpec, name: str) -> str | None:
    values = [val for key, val in current.params if key == name]
    return values[-1] if values else None


def resolve_url(current: RequestSpec, reference: str) -> str:
    """Resolve a possibly relative URL against the request that produced the page."""
    return urljoin(current.url, reference)


async def iter_pages(
    send: Send,
    first: RequestSpec,
    strategy: PaginationStrategy,
    *,
    max_pages: int | None = None,
) -> AsyncIterator[httpx.Response]:
    """Yield each page response. Stops at the last page, at ``max_pages``, or on error."""
    current = first
    seen = {_fingerprint(first)}
    pages = 0
    while True:
        response = await send(current)
        pages += 1
        yield response
        if max_pages is not None and pages >= max_pages:
            return
        following = strategy.next_request(current, response)
        if following is None:
            return
        fingerprint = _fingerprint(following)
        if fingerprint in seen:
            # The server pointed back at a page we already fetched. Stop rather than loop.
            raise PaginationError("next page repeats an earlier request")
        seen.add(fingerprint)
        current = following


async def iter_items(
    send: Send,
    first: RequestSpec,
    strategy: PaginationStrategy,
    *,
    max_pages: int | None = None,
) -> AsyncIterator[JsonValue]:
    """Yield every record across pages, one at a time."""
    async for response in iter_pages(send, first, strategy, max_pages=max_pages):
        for item in strategy.items(response):
            yield item


def _fingerprint(spec: RequestSpec) -> tuple[object, ...]:
    body = json.dumps(spec.json_body, sort_keys=True, default=str)
    return (spec.method, spec.url, spec.params, spec.headers, spec.content, body)
