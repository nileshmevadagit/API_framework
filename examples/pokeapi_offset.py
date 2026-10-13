"""Walk the PokeAPI species list, following the "next" URL in each response body.

PokeAPI paginates with a full next URL in the body, so the strategy is NextUrlPagination.
The data is static and no key is needed. PokeAPI asks clients to cache responses, so keep
the page count small for demos.

Run with: uv run python examples/pokeapi_offset.py
"""

from __future__ import annotations

import asyncio

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.endpoints import build_request
from apiframework.pagination import NextUrlPagination


async def main() -> None:
    config = parse_config(
        {
            "apis": {
                "pokeapi": {
                    "base_url": "https://pokeapi.co/api/v2",
                    "endpoints": {
                        "pokemon": {
                            "method": "GET",
                            "path": "/pokemon",
                            "params": {"limit": 20, "offset": 0},
                            "pagination": {
                                "type": "next_url",
                                "url_path": "next",
                                "items_path": "results",
                            },
                        }
                    },
                }
            }
        }
    )
    api = config.api("pokeapi")
    async with AsyncClient(api) as client:
        spec = build_request(client, api.endpoints["pokemon"])
        names = [
            str(item["name"])
            async for item in client.iter_items(
                spec, NextUrlPagination(url_path="next", items_path="results"), max_pages=3
            )
            if isinstance(item, dict)
        ]

    print(f"fetched {len(names)} Pokémon names across 3 pages:")
    print(", ".join(names))


if __name__ == "__main__":
    asyncio.run(main())
