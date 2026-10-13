"""Endpoints: turn config (paging, endpoint definitions) into strategies and requests.

Nothing here sends a request. ``build_request`` returns a ``RequestSpec`` that a client sends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from apiframework.config import (
    CursorPaging,
    HasMorePaging,
    LinkHeaderPaging,
    NextUrlPaging,
    OffsetPaging,
    PagePaging,
)
from apiframework.pagination import (
    CursorPagination,
    HasMorePagination,
    LinkHeaderPagination,
    NextUrlPagination,
    OffsetPagination,
    PagePagination,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

    from apiframework.client import ParamValue
    from apiframework.config import EndpointConfig, PagingConfig
    from apiframework.pagination import PaginationStrategy
    from apiframework.request import HTTPMethod, RequestSpec


class RequestBuilder(Protocol):
    def build_request(
        self,
        method: HTTPMethod,
        path: str,
        *,
        params: dict[str, ParamValue] | None = None,
        headers: dict[str, str] | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        cost: int = 1,
        url_template: str | None = None,
    ) -> RequestSpec: ...


def build_strategy(paging: PagingConfig) -> PaginationStrategy:
    """Create the pagination strategy a config section describes."""
    if isinstance(paging, OffsetPaging):
        return OffsetPagination(
            limit=paging.limit,
            limit_param=paging.limit_param,
            offset_param=paging.offset_param,
            items_path=paging.items_path,
        )
    if isinstance(paging, PagePaging):
        return PagePagination(
            page_param=paging.page_param, start=paging.start, items_path=paging.items_path
        )
    if isinstance(paging, CursorPaging):
        return CursorPagination(
            cursor_path=paging.cursor_path,
            cursor_param=paging.cursor_param,
            items_path=paging.items_path,
        )
    if isinstance(paging, HasMorePaging):
        return HasMorePagination(
            more_path=paging.more_path,
            cursor_field=paging.cursor_field,
            cursor_param=paging.cursor_param,
            items_path=paging.items_path,
        )
    if isinstance(paging, LinkHeaderPaging):
        return LinkHeaderPagination(rel=paging.rel)
    if isinstance(paging, NextUrlPaging):
        return NextUrlPagination(url_path=paging.url_path, items_path=paging.items_path)
    raise TypeError(f"unhandled paging config: {type(paging).__name__}")


def build_request(
    client: RequestBuilder,
    endpoint: EndpointConfig,
    params: dict[str, ParamValue] | None = None,
) -> RequestSpec:
    """Build the request for ``endpoint``. ``params`` override the endpoint's own params."""
    merged: dict[str, ParamValue] = {**endpoint.params, **(params or {})}
    return client.build_request(
        endpoint.method,
        endpoint.path,
        params=merged,
        headers=endpoint.headers,
        cost=endpoint.cost,
        url_template=endpoint.path,
    )
