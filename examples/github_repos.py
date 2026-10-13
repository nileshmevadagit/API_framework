"""List a user's public repositories from the GitHub REST API.

Shows Link-header pagination and the rate-limit headers GitHub returns. No token is needed,
but unauthenticated calls are limited to 60 an hour. Set GITHUB_TOKEN in your environment
to raise that to 5,000 an hour.

Run with: uv run python examples/github_repos.py [username]
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.endpoints import build_request
from apiframework.pagination import LinkHeaderPagination


async def main(user: str) -> None:
    auth: dict[str, Any] = {}
    if os.environ.get("GITHUB_TOKEN"):
        auth = {"type": "bearer", "token": "${GITHUB_TOKEN}"}

    config = parse_config(
        {
            "apis": {
                "github": {
                    "base_url": "https://api.github.com",
                    "headers": {"Accept": "application/vnd.github+json"},
                    "auth": auth or None,
                    "endpoints": {
                        "repos": {
                            "method": "GET",
                            "path": f"/users/{user}/repos",
                            "params": {"per_page": 100, "type": "owner"},
                            "pagination": {"type": "link_header"},
                        }
                    },
                }
            }
        }
    )
    api = config.api("github")
    async with AsyncClient(api) as client:
        spec = build_request(client, api.endpoints["repos"])
        names: list[str] = []
        async for repo in client.iter_items(spec, LinkHeaderPagination(), max_pages=5):
            assert isinstance(repo, dict)
            names.append(str(repo["full_name"]))

        probe = await client.get("/rate_limit")
        remaining = probe.headers.get("X-RateLimit-Remaining", "unknown")

    print(f"{len(names)} repositories for {user}:")
    for name in names[:10]:
        print(f"  {name}")
    print(f"requests left in this hour's quota: {remaining}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "octocat"))
