"""State stores. Only quota counters, tokens, checkpoints and ETags are kept here."""

from __future__ import annotations

from apiframework.state.base import StateStore
from apiframework.state.memory import MemoryStateStore

__all__ = ["MemoryStateStore", "StateStore"]
