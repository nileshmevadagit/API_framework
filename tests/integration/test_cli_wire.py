"""The CLI against the real JSONPlaceholder API. Needs internet access."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from apiframework.cli import EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

JSONPLACEHOLDER = os.environ.get("JSONPLACEHOLDER_URL", "https://jsonplaceholder.typicode.com")


def test_cli_pages_through_every_post(tmp_path: Path) -> None:
    job = tmp_path / "job.yaml"
    output = tmp_path / "posts.jsonl"
    job.write_text(
        f"""
apis:
  jp:
    base_url: {JSONPLACEHOLDER}
    endpoints:
      posts:
        method: GET
        path: /posts
        params: {{_limit: 10, _page: 1}}
        pagination: {{type: page, page_param: _page}}
jobs:
  all:
    api: jp
    endpoint: posts
    output: {output}
""",
        encoding="utf-8",
    )
    assert main(["run", str(job)]) == EXIT_OK
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 100
    assert len({record["id"] for record in records}) == 100
