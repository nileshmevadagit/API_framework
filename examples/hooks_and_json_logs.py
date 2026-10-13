"""Metrics hooks and JSON log lines, the two ways to watch what a client is doing.

Hooks are plain callbacks that get one event per request, retry, response and rate-limit
wait. The access log is written through the standard logging module, and JsonFormatter turns
each record into one JSON object. The library never configures logging itself, so this
example attaches the handler.

Run with: uv run python examples/hooks_and_json_logs.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.hooks import Hooks, ResponseEvent
from apiframework.logging_json import JsonFormatter


async def main() -> None:
    responses: list[ResponseEvent] = []
    hooks = Hooks(on_response=responses.append)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("apiframework")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    config = parse_config({"apis": {"jp": {"base_url": "https://jsonplaceholder.typicode.com"}}})
    async with AsyncClient(config.api("jp"), hooks=hooks) as client:
        await client.get("/posts/1")
        await client.get("/users/1")

    logger.removeHandler(handler)
    total = sum(event.latency_s for event in responses)
    print(f"hook saw {len(responses)} responses, {total * 1000:.0f} ms in total", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
