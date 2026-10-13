"""Shared pytest fixtures.

Rules (see CLAUDE.md): no real network in unit tests (use respx), and never sleep.
Use the ``clock`` fixture wherever time matters.
"""

from __future__ import annotations

import pytest

from fakes import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
