# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Integration tests against JSONPlaceholder covering every HTTP verb, nested
  routes and the non-persisted write behaviour (`tests/integration/`, marker
  `integration`; base URL overridable with `JSONPLACEHOLDER_URL`).
- Config models (`Config`, `ApiConfig`, `Defaults`, `Timeouts`, `ProxyConfig`, `TLSConfig`) with
  per-API overrides, `parse_config` and `load_config` (YAML, optional `yaml` extra).
- `${ENV_VAR}` secret references, plus rejection of pasted keys in headers and URLs.
- `AsyncClient` and sync `Client` for one API: verbs, params, JSON and raw bodies, and a
  middleware chain (`middleware/chain.py`) that is empty for now.
- httpx transport with always-on timeouts, forward proxy with `no_proxy`, SOCKS (optional
  `socks` extra), CA bundles and client certificates.
- Dev dependency: `types-PyYAML`, for mypy strict on the YAML loader.
- State stores: `SQLiteStateStore` (stdlib, WAL, safe across processes) and `RedisStateStore`
  (optional `redis` extra; counters updated by one Lua script). The contract suite runs against
  all three stores, with Redis under the `integration` marker.
- `state:` config section (`memory`, `sqlite` or `redis`; the Redis URL must be `${ENV_VAR}`)
  and `build_state_store()`.
- Observability: an access log (one record per call, URL template only, outermost in the chain),
  `Hooks` for request, response, retry and rate-limit events, `JsonFormatter` for applications to
  attach, and an optional OpenTelemetry span (`telemetry=True`, `otel` extra). Headers are redacted
  before any log; bodies are logged only at DEBUG with `log_bodies=True`.
- Endpoints: `apis.<name>.endpoints` config (method, path, params, headers, pagination, cost),
  with paging types offset, page, cursor, link_header and next_url (`endpoints.py`).
- Pagination type `has_more` (`HasMorePagination`): a `has_more` flag in the body, with the
  last record's `id` sent as `starting_after`. Used by Stripe-style list endpoints.
- CLI: `apiframework run job.yaml [--job NAME] [-v]` writes records as JSON lines to stdout or
  each job's `output` file. Exit codes: 0 success, 1 job failed, 2 bad job file or environment.
  Also `python -m apiframework`.
- `jobs:` and `observability:` config sections. Each job names an API endpoint and its params.
- dlt adapter (`apiframework.adapters.dlt.records_resource`, `dlt` extra).
- Dockerfile for the CLI: python:3.12-slim, non-root user, runtime extras only.
- `Client.iter_items` and `Client.build_request` for the sync client.
- README rewritten as a user guide (install, quick start, CLI, configuration reference, errors,
  observability, limitations). Developer setup kept under "Development".
- Examples: GitHub repos, PokeAPI pagination, JSONPlaceholder CRUD, hooks and JSON logs.
- Design doc layout updated to the modules that exist.

### Fixed
- An empty environment variable used as a secret (for example `TOKEN=""`) produced an invalid
  `Bearer ` header and failed inside httpx. It is now a `ConfigError` at load time, which names
  the variable.
- `url_template` argument on `request()` and `build_request()`, so logs and spans show `/users/{id}`
  rather than the ID.
- Auth: api key (header or query), bearer, basic, OAuth2 client credentials (cached, refreshed
  before expiry, single-flight, one retry after a 401) and custom signing callables.
- Retries: response classifier (ok, retryable, failure), exponential backoff with full jitter,
  `Retry-After` in both forms, and idempotency rules (POST and PATCH only with opt-in or an
  `Idempotency-Key`). Non-retryable responses raise `HTTPStatusError`.
- Pagination: offset, page, cursor, Link header and next-URL strategies, with `iter_pages` and
  `iter_items` on the client. Loops are detected and raise `PaginationError`.
- Rate limits: per-second token bucket, and hour and day quota windows in the StateStore.
  Server `RateLimit-*` headers correct the local counter. Limiters are shared by key through
  `RateLimiters`. Requests can declare a cost above 1.
- Errors: `ResponseRejected` (classifier rejected a 2xx) and `PaginationError`.
- Project scaffold: packaging (uv + hatchling), ruff, mypy --strict, pytest,
  pre-commit, GitHub Actions (CI + nightly integration), docker-compose services,
  VS Code workspace settings, CLAUDE.md.
- Core types: `RequestSpec` (frozen, `clone()`), `Middleware` protocol, `Clock`
  protocol with `SystemClock`, `ApiError` hierarchy, `StateStore` protocol with
  an in-memory implementation and a shared contract test suite.
