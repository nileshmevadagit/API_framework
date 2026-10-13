"""SQLite StateStore: one machine, no extra dependency, durable across restarts.

Uses the stdlib ``sqlite3`` module. Each call runs on a worker thread via
``asyncio.to_thread`` so the event loop never blocks on disk. A lock serialises use of the
single connection inside this process. Across processes, WAL mode and ``BEGIN IMMEDIATE``
keep counter updates correct on the same file.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from typing import TYPE_CHECKING

from apiframework.clock import SystemClock

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue

    from apiframework.clock import Clock

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at REAL
)
"""


class SQLiteStateStore:
    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,  # explicit BEGIN/COMMIT below
            timeout=10.0,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute(SCHEMA)

    async def get(self, key: str) -> JsonValue | None:
        return await asyncio.to_thread(self._get, key)

    async def set(self, key: str, value: JsonValue, *, expires_at: float | None = None) -> None:
        await asyncio.to_thread(self._set, key, value, expires_at)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def incr(self, key: str, amount: int = 1, *, expires_at: float | None = None) -> int:
        return await asyncio.to_thread(self._incr, key, amount, expires_at)

    async def aclose(self) -> None:
        await asyncio.to_thread(self._close)

    # Synchronous bodies. Each runs on one worker thread at a time, under the lock.

    def _get(self, key: str) -> JsonValue | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM state WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, expires_at = row
            if self._expired(expires_at):
                self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
                return None
            decoded: JsonValue = json.loads(value)
            return decoded

    def _set(self, key: str, value: JsonValue, expires_at: float | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), expires_at),
            )

    def _delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM state WHERE key = ?", (key,))

    def _incr(self, key: str, amount: int, expires_at: float | None) -> int:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT value, expires_at FROM state WHERE key = ?", (key,)
                ).fetchone()
                if row is not None and not self._expired(row[1]):
                    current = json.loads(row[0])
                    if isinstance(current, bool) or not isinstance(current, int):
                        raise TypeError(f"state key {key!r} does not hold an integer")
                    new = current + amount
                    # A live counter keeps its original expiry; only new windows set one.
                    self._conn.execute(
                        "UPDATE state SET value = ? WHERE key = ?", (json.dumps(new), key)
                    )
                else:
                    new = amount
                    self._conn.execute(
                        "INSERT OR REPLACE INTO state (key, value, expires_at) VALUES (?, ?, ?)",
                        (key, json.dumps(new), expires_at),
                    )
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
            return new

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and self._clock.now() >= expires_at

    def _close(self) -> None:
        with self._lock:
            self._conn.close()
