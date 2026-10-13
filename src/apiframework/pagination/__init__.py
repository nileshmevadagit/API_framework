"""Pagination strategies and the iterators that drive them."""

from __future__ import annotations

from apiframework.pagination.base import PaginationStrategy, iter_items, iter_pages
from apiframework.pagination.strategies import (
    CursorPagination,
    LinkHeaderPagination,
    NextUrlPagination,
    OffsetPagination,
    PagePagination,
)

__all__ = [
    "CursorPagination",
    "LinkHeaderPagination",
    "NextUrlPagination",
    "OffsetPagination",
    "PagePagination",
    "PaginationStrategy",
    "iter_items",
    "iter_pages",
]
