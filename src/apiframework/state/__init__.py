"""State stores. Only quota counters, tokens, checkpoints and ETags are kept here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.config import MemoryState, RedisState, SQLiteState
from apiframework.state.base import StateStore
from apiframework.state.memory import MemoryStateStore
from apiframework.state.redis import RedisStateStore
from apiframework.state.sqlite import SQLiteStateStore

if TYPE_CHECKING:
    from apiframework.clock import Clock
    from apiframework.config import StateConfig

__all__ = [
    "MemoryStateStore",
    "RedisStateStore",
    "SQLiteStateStore",
    "StateStore",
    "build_state_store",
]


def build_state_store(config: StateConfig, *, clock: Clock) -> StateStore:
    """Create the store named in a config's ``state`` section. Share the result across clients."""
    if isinstance(config, SQLiteState):
        return SQLiteStateStore(config.path, clock=clock)
    if isinstance(config, RedisState):
        return RedisStateStore(config.url.get_secret_value(), clock=clock, prefix=config.prefix)
    if isinstance(config, MemoryState):
        return MemoryStateStore(clock)
    raise TypeError(f"unhandled state config: {type(config).__name__}")
