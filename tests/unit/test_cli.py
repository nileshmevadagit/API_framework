"""The CLI: job file in, JSON lines out, and exit codes. HTTP is mocked with respx."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from apiframework.cli import EXIT_BAD_INPUT, EXIT_JOB_FAILED, EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    import respx

BASE = "https://api.test/v1"

JOB_FILE = """\
apis:
  jp:
    base_url: {base}
    endpoints:
      posts:
        method: GET
        path: /posts
        params: {{_limit: 2, _page: 1}}
        pagination: {{type: page, page_param: _page}}
      single:
        method: GET
        path: /single
      missing:
        method: GET
        path: /missing
jobs:
  all_posts:
    api: jp
    endpoint: posts
    output: {output}
  one:
    api: jp
    endpoint: single
  broken:
    api: jp
    endpoint: missing
"""


def _job_file(tmp_path: Path, output: Path) -> Path:
    path = tmp_path / "job.yaml"
    path.write_text(JOB_FILE.format(base=BASE, output=output), encoding="utf-8")
    return path


def _mock_posts(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/posts", params={"_limit": "2", "_page": "1"}).mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    respx_mock.get(f"{BASE}/posts", params={"_limit": "2", "_page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )
    respx_mock.get(f"{BASE}/posts", params={"_limit": "2", "_page": "3"}).mock(
        return_value=httpx.Response(200, json=[])
    )


def test_paginated_job_writes_json_lines_to_its_output(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _mock_posts(respx_mock)
    output = tmp_path / "posts.jsonl"
    job = _job_file(tmp_path, output)

    code = main(["run", str(job), "--job", "all_posts"])

    assert code == EXIT_OK
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert records == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_unpaginated_job_writes_the_body_to_stdout(
    tmp_path: Path, respx_mock: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    respx_mock.get(f"{BASE}/single").mock(return_value=httpx.Response(200, json=[{"n": 1}]))
    job = _job_file(tmp_path, tmp_path / "unused.jsonl")

    code = main(["run", str(job), "--job", "one"])

    assert code == EXIT_OK
    assert capsys.readouterr().out == '{"n": 1}\n'


def test_failed_job_exits_one_with_a_message(
    tmp_path: Path, respx_mock: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    respx_mock.get(f"{BASE}/missing").mock(return_value=httpx.Response(404))
    job = _job_file(tmp_path, tmp_path / "unused.jsonl")

    code = main(["run", str(job), "--job", "broken"])

    assert code == EXIT_JOB_FAILED
    assert "HTTP 404" in capsys.readouterr().err


def test_unknown_job_name_is_bad_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = _job_file(tmp_path, tmp_path / "unused.jsonl")
    code = main(["run", str(job), "--job", "nope"])
    assert code == EXIT_BAD_INPUT
    assert "no job named 'nope'" in capsys.readouterr().err


def test_job_file_that_is_not_a_mapping_is_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = tmp_path / "job.yaml"
    job.write_text("- a\n- list\n", encoding="utf-8")
    assert main(["run", str(job)]) == EXIT_BAD_INPUT
    assert "top level must be a mapping" in capsys.readouterr().err


def test_missing_job_file_is_a_job_failure_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", str(tmp_path / "absent.yaml")]) == EXIT_JOB_FAILED
    assert "absent.yaml" in capsys.readouterr().err
