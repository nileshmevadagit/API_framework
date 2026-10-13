"""Redis store setup that does not need a server. The behaviour tests are in integration."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from apiframework.state import RedisStateStore

if TYPE_CHECKING:
    from pathlib import Path

    from fakes import FakeClock


def test_missing_extra_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    with pytest.raises(ImportError, match=r"apiframework\[redis\]"):
        RedisStateStore("redis://localhost:6379/0", clock=clock)


def test_build_state_store_maps_each_config_type(clock: FakeClock, tmp_path: Path) -> None:
    from apiframework.config import MemoryState, SQLiteState
    from apiframework.state import MemoryStateStore, SQLiteStateStore, build_state_store

    assert isinstance(build_state_store(MemoryState(), clock=clock), MemoryStateStore)
    sqlite_store = build_state_store(
        SQLiteState(type="sqlite", path=str(tmp_path / "s.db")), clock=clock
    )
    assert isinstance(sqlite_store, SQLiteStateStore)
