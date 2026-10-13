# CLAUDE.md — API_framework (`apiframework`)

Python library for pulling data out of HTTP APIs reliably: retries, pagination,
rate limits, durable quotas, auth, proxies. Loading data is out of scope (handed
to dlt via an optional adapter).

**Source of truth:** `design_doc/design.md`. If code and the design doc
disagree, flag it rather than silently picking one. The `.docx` in the same
folder is the original Word copy; don't edit it.

Setup and prerequisites are in `README.md`. Development happens on macOS
(Apple Silicon) in VS Code, using `uv` for everything Python.

## Commands

```bash
uv sync                           # create/refresh .venv with dev deps (Python from .python-version)
uv run pytest                     # unit tests (default markers exclude integration/costs_money)
uv run pytest -m integration      # needs `docker compose up -d`
uv run ruff check . --fix && uv run ruff format .
uv run mypy                       # strict; config in pyproject.toml
uv run pre-commit run --all-files
docker compose up -d              # httpbin :8080, redis :6379, mitmproxy :8888
```

Always run ruff, mypy and the unit tests before calling a task done.
Never call `pip` or `python` directly; use `uv run` / `uv add`.

## Layout

```
src/apiframework/
  client.py        # AsyncClient (core) + Client (thin sync wrapper)
  config.py        # Pydantic models; YAML + Python both load into these
  endpoints.py     # endpoint definitions -> RequestSpec
  request.py       # RequestSpec (frozen; .clone(**overrides))
  errors.py        # ApiError hierarchy
  clock.py         # Clock protocol + SystemClock (now / monotonic / sleep)
  cli.py           # `apiframework run job.yaml`
  middleware/      # base.py: Middleware protocol; logging, retry, auth, ratelimit
  auth/            # api_key, bearer, basic, oauth2, custom
  pagination/      # offset, page, cursor, link_header, next_url
  codecs/          # json, form, xml, raw
  state/           # base.py: StateStore protocol; memory.py (sqlite, redis to come)
  adapters/dlt.py  # optional extra [dlt]
tests/fakes.py     # FakeClock (imported as `from fakes import ...`)
tests/unit/        # mirrors src paths; respx-mocked
tests/unit/state/  # test_store_contract.py: one suite for every StateStore
tests/integration/ # @pytest.mark.integration
examples/  design_doc/  .github/workflows/  .vscode/
```

Create modules as milestones need them. `request.py` and `clock.py` are not in the
design doc's layout list yet; they were added in milestone 1 and the design doc
needs the same update before v0.5.

## Architecture invariants (do not break these)

- **Middleware order is fixed:** logging → retry → auth → ratelimit → transport.
  Retry sits *outside* auth and the limiter so every retry gets a fresh token
  and is counted against quota. Never reorder without updating the design doc.
- **Middleware contract:** `async def __call__(self, req: RequestSpec, call_next) -> Response`.
  One concern per class; each testable alone.
- **Async core, sync wrapper.** All logic is async. The sync `Client` only
  wraps; it must never contain its own logic.
- **RequestSpec is immutable.** Frozen model, changed via `.clone(**overrides)`.
  Pagination and (future) sharding depend on this.
- **Pagination state lives in the iterator,** never on the client.
- **Rate limiters are looked up by key** (api / endpoint), not owned by a client,
  so several clients and future shards can share one quota.
- **Throughput ≠ quota.** Per-second limits use a token bucket (in memory).
  Hour/day windows are counters in a `StateStore`. Server `RateLimit-*` /
  `X-RateLimit-*` headers override local counters. Requests may cost >1 unit.
- **Retry rules:** retry only 408, 425, 429, 500, 502, 503, 504, connection
  errors, read timeouts. Other 4xx fail immediately. Exponential backoff with
  full jitter; `Retry-After` (seconds and HTTP-date) always wins.
  GET/PUT/DELETE/HEAD retry by default; POST/PATCH only with opt-in or an
  `Idempotency-Key`.
- **Response classifier decides ok / retryable / failure,** not the status code
  alone (GraphQL and JSON-RPC return 200 with errors).
- **OAuth2 refresh is single-flight:** concurrent expiries trigger one refresh
  (use an `asyncio.Lock`). Refresh slightly before expiry; retry once on 401.
- **No module-level mutable globals.** Two clients in one process must never
  interfere. Timeouts are always set.
- **No response data in state.** StateStore holds only quota counters, tokens,
  checkpoints, ETags.

## Dependencies

- Required: `httpx`, `pydantic` (v2). Nothing else. Do not add a required
  dependency without asking.
- Optional extras (in pyproject): `yaml`, `socks`, `redis`, `otel`, `dlt`, `aws`.
  Import optional packages lazily inside the module that needs them and raise a
  clear `ImportError` naming the extra (`pip install apiframework[redis]`).
- No `requests`, no `tenacity` — retry logic is intentionally owned here.
- SQLite store uses stdlib `sqlite3` (run via `asyncio.to_thread`).
- Commit `uv.lock` whenever dependencies change.

## Conventions

- Python 3.10–3.13. Use `from __future__ import annotations`; no 3.11+ only
  syntax (`except*`, `typing.Self` — use `typing_extensions` if needed).
- `mypy --strict` clean. Public API fully typed. No `Any` leaking from public
  functions. No `# type: ignore` / `# noqa` without a reason comment.
- Protocols (`typing.Protocol`) for pluggable pieces: `Middleware`,
  `PaginationStrategy`, `Codec`, `StateStore`, `Clock`, `AuthHandler`.
- Errors: everything raised to users subclasses `ApiError`
  (`HTTPStatusError`, `RetryExhausted`, `QuotaExhausted`, `AuthError`,
  `ConfigError`). `QuotaExhausted` carries the reset time.
- Logging: `logging.getLogger("apiframework...")`. Never configure handlers.
  Log the URL *template*, not the filled URL. Redact auth headers, cookies,
  API keys by default. Bodies only at DEBUG and only when enabled.
- Config: secrets only as `${ENV_VAR}` references. The loader must reject
  values that look like pasted keys. Never read or print `.env`.
- Small focused modules; prefer composition over inheritance. Line length 100.

## Testing

- Unit tests mock HTTP with `respx`. No real network in unit tests.
- **Never `asyncio.sleep` / `time.sleep` in tests.** Inject a fake `Clock`
  (and a fake sleeper) so window rollover and backoff run instantly.
- Seed or inject randomness for jitter so backoff tests are deterministic.
- `pytest-asyncio` runs in auto mode: write `async def test_...` directly.
- Markers: `integration` (docker-compose services and public APIs:
  JSONPlaceholder, httpbin, GitHub, PokéAPI), `costs_money` (real cloud; never
  in default CI). Default run excludes both.
- Every bug fix gets a regression test. Every retry path, both Retry-After
  formats, and each pagination strategy must have explicit tests.
- StateStore implementations share one parametrized contract test suite.

## Git

- Don't commit or push unless asked. Work on a branch, never directly on `main`.
- Conventional Commits (`feat(retry): ...`, `fix: ...`, `test: ...`).
- Keep personal tool files out of the repo: `.claude/`, `CLAUDE.local.md`,
  `.env`, and `.vscode/` beyond the three shared files are git-ignored.
- Update `CHANGELOG.md` (Unreleased) and this file when commands, layout or
  rules change.

## Scope guardrails

Not in v1: sharding (design for it, don't build it), gRPC, WebSockets,
SSE, storing response data, anything needing a cloud account. If a task
drifts into these, stop and ask.

## Status

Scaffold done (packaging, CI, tooling). Milestone 1 done (on branch `feat/core-types`,
not committed): `RequestSpec`, `Middleware` protocol, `Clock`, `errors.py`,
in-memory `StateStore`, and the shared StateStore contract suite. Next, in order:
2. Config models + client + transport (proxy, TLS)
3. Auth → retries (with response classifier) → pagination → rate limits (memory)
4. SQLite/Redis stores → hooks/logging/OTel → CLI/Docker/dlt adapter → docs

Update this section as milestones land.
