"""``apiframework run job.yaml``: run jobs from a job file and write records as JSON lines.

Exit codes: 0 all jobs finished, 1 a job failed at runtime, 2 the job file or environment is
wrong. Logs go to stderr; records go to stdout, or to each job's ``output`` file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from apiframework.client import AsyncClient
from apiframework.clock import SystemClock
from apiframework.config import EndpointConfig, load_config
from apiframework.endpoints import build_request, build_strategy
from apiframework.errors import ApiError, ConfigError
from apiframework.ratelimit import RateLimiters
from apiframework.state import RedisStateStore, SQLiteStateStore, build_state_store

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apiframework.request import RequestSpec

EXIT_OK = 0
EXIT_JOB_FAILED = 1
EXIT_BAD_INPUT = 2
LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO}
CLI_HANDLER = "apiframework-cli"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apiframework", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run jobs from a job file")
    run.add_argument("job_file", help="YAML file with apis, endpoints and jobs")
    run.add_argument(
        "--job",
        action="append",
        dest="jobs",
        metavar="NAME",
        help="run only this job (repeatable); default is every job in the file",
    )
    run.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    try:
        return asyncio.run(_run(args.job_file, args.jobs))
    except ConfigError as exc:
        print(f"apiframework: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except ImportError as exc:
        print(f"apiframework: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except (ApiError, OSError) as exc:
        print(f"apiframework: {exc}", file=sys.stderr)
        return EXIT_JOB_FAILED


def _configure_logging(verbosity: int) -> None:
    """The CLI is an application, so it may configure logging. The library never does."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.set_name(CLI_HANDLER)
    logger = logging.getLogger("apiframework")
    for existing in list(logger.handlers):
        if existing.name == CLI_HANDLER:  # replace the handler from an earlier call
            logger.removeHandler(existing)
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVELS.get(verbosity, logging.DEBUG))


async def _run(job_file: str, selected: list[str] | None) -> int:
    cfg = load_config(job_file)
    names = selected if selected else list(cfg.jobs)
    if not names:
        raise ConfigError(f"{job_file}: no jobs defined")
    for name in names:
        if name not in cfg.jobs:
            raise ConfigError(f"no job named {name!r} in {job_file}")

    clock = SystemClock()
    state = build_state_store(cfg.state, clock=clock)
    limiters = RateLimiters(state=state, clock=clock)  # one quota per API, shared by its jobs
    clients: dict[str, AsyncClient] = {}
    try:
        for name in names:
            job = cfg.jobs[name]
            if job.api not in clients:
                clients[job.api] = AsyncClient(
                    cfg.api(job.api),
                    state=state,
                    rate_limiters=limiters,
                    clock=clock,
                    log_bodies=cfg.observability.log_bodies,
                    telemetry=cfg.observability.telemetry,
                )
            client = clients[job.api]
            endpoint = cfg.api(job.api).endpoints[job.endpoint]
            spec = build_request(client, endpoint, job.params)
            if job.output is None:
                await _write_job(name, client, endpoint, spec, job.max_pages, sys.stdout)
            else:
                with _open_output(job.output) as handle:
                    await _write_job(name, client, endpoint, spec, job.max_pages, handle)
    finally:
        for client in clients.values():
            await client.aclose()
        if isinstance(state, (SQLiteStateStore, RedisStateStore)):
            await state.aclose()
    return EXIT_OK


def _open_output(path: str) -> TextIO:
    # Create missing folders, so `out/customers.jsonl` works on a fresh checkout.
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return open(path, "w", encoding="utf-8")  # closed by the caller's with-block


async def _write_job(
    name: str,
    client: AsyncClient,
    endpoint: EndpointConfig,
    spec: RequestSpec,
    max_pages: int | None,
    out: TextIO,
) -> None:
    count = 0
    if endpoint.pagination is None:
        response = await client.send(spec)
        body = response.json()
        records = body if isinstance(body, list) else [body]
        for record in records:
            out.write(json.dumps(record) + "\n")
            count += 1
    else:
        strategy = build_strategy(endpoint.pagination)
        async for record in client.iter_items(spec, strategy, max_pages=max_pages):
            out.write(json.dumps(record) + "\n")
            count += 1
    logging.getLogger("apiframework.cli").info("job %s wrote %d records", name, count)
