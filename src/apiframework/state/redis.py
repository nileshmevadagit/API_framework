"""Redis StateStore: several workers share one quota. Needs the ``redis`` extra.

Each value is stored in an envelope ``{"v": value, "exp": "<epoch>"}``. Expiry is judged
against the injected clock, not the Redis server's clock, so the behaviour matches the
memory and SQLite stores. Redis TTLs are set only as cleanup, from the same clock.

``incr`` is one Lua script, so the read, check and write are atomic across processes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from apiframework.clock import SystemClock

if TYPE_CHECKING:
    from pydantic import JsonValue

    from apiframework.clock import Clock

# KEYS[1] = key; ARGV[1] = amount; ARGV[2] = now; ARGV[3] = new expiry or "".
INCR_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
local amount = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local current = 0
local exp = nil
local live = false
if raw then
  local entry = cjson.decode(raw)
  -- JSON null decodes to cjson.null, not nil, so test the type of the expiry.
  local stored = entry['exp']
  local has_exp = type(stored) == 'string'
  if (not has_exp) or tonumber(stored) > now then
    live = true
    if has_exp then
      exp = stored
    end
    local v = entry['v']
    if type(v) ~= 'number' or math.floor(v) ~= v then
      return redis.error_reply('NOT_INTEGER')
    end
    current = v
  end
end
if not live and ARGV[3] ~= '' then
  exp = ARGV[3]
end
local new = current + amount
local entry = {v = new}
if exp ~= nil then
  entry['exp'] = exp
end
redis.call('SET', KEYS[1], cjson.encode(entry))
if exp ~= nil then
  local ttl = math.max(1, math.ceil((tonumber(exp) - now) * 1000))
  redis.call('PEXPIRE', KEYS[1], ttl)
end
return new
"""


def _redis_asyncio() -> Any:
    # Imported here, not at module top: redis is an optional extra.
    try:
        import redis.asyncio
    except ImportError as exc:
        raise ImportError("Redis store needs redis: pip install apiframework[redis]") from exc
    return redis.asyncio


def _format_expiry(expires_at: float) -> str:
    return f"{expires_at:.6f}"


class RedisStateStore:
    def __init__(
        self,
        url: str,
        *,
        clock: Clock | None = None,
        prefix: str = "apiframework:",
    ) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._prefix = prefix
        self._redis = _redis_asyncio().Redis.from_url(url)
        self._incr_script = self._redis.register_script(INCR_SCRIPT)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _expired(self, expires_at: str | None) -> bool:
        return expires_at is not None and self._clock.now() >= float(expires_at)

    async def get(self, key: str) -> JsonValue | None:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        entry = json.loads(raw)
        if self._expired(entry.get("exp")):
            await self.delete(key)
            return None
        value: JsonValue = entry["v"]
        return value

    async def set(self, key: str, value: JsonValue, *, expires_at: float | None = None) -> None:
        if expires_at is None:
            await self._redis.set(self._key(key), json.dumps({"v": value}))
        else:
            envelope = {"v": value, "exp": _format_expiry(expires_at)}
            await self._redis.set(self._key(key), json.dumps(envelope), px=self._ttl_ms(expires_at))

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    async def incr(self, key: str, amount: int = 1, *, expires_at: float | None = None) -> int:
        expiry = "" if expires_at is None else _format_expiry(expires_at)
        try:
            result = await self._incr_script(
                keys=[self._key(key)],
                args=[amount, self._clock.now(), expiry],
            )
        except Exception as exc:
            if "NOT_INTEGER" in str(exc):
                raise TypeError(f"state key {key!r} does not hold an integer") from exc
            raise
        return int(result)

    async def aclose(self) -> None:
        await self._redis.aclose()

    def _ttl_ms(self, expires_at: float) -> int:
        return max(1, int((expires_at - self._clock.now()) * 1000) + 1)
