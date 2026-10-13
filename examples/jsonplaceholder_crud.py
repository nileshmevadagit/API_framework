"""Every HTTP verb through one client, against JSONPlaceholder.

JSONPlaceholder accepts writes and echoes them back, but it does not store them. A created
record can't be read back, so the last step shows that. Use restful-api.dev or your own
server when you need writes that persist.

Run with: uv run python examples/jsonplaceholder_crud.py
"""

from __future__ import annotations

import asyncio

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.errors import HTTPStatusError


async def main() -> None:
    config = parse_config({"apis": {"jp": {"base_url": "https://jsonplaceholder.typicode.com"}}})
    async with AsyncClient(config.api("jp")) as client:
        read = await client.get("/posts/1")
        print("GET    /posts/1        ->", read.status_code, read.json()["title"][:40])

        created = await client.post("/posts", json={"title": "hello", "body": "world", "userId": 1})
        print("POST   /posts          ->", created.status_code, "id", created.json()["id"])

        replaced = await client.put(
            "/posts/1", json={"id": 1, "title": "replaced", "body": "all fields", "userId": 1}
        )
        print("PUT    /posts/1        ->", replaced.status_code, replaced.json()["title"])

        patched = await client.patch("/posts/1", json={"title": "patched"})
        print("PATCH  /posts/1        ->", patched.status_code, patched.json()["title"])

        deleted = await client.delete("/posts/1")
        print("DELETE /posts/1        ->", deleted.status_code, deleted.json())

        try:
            await client.get(f"/posts/{created.json()['id']}")
        except HTTPStatusError as exc:
            print("GET    /posts/101      ->", exc.status_code, "(writes are not stored)")


if __name__ == "__main__":
    asyncio.run(main())
