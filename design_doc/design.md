# API Client Framework – Design Doc

**Author:** Nilesh Mevada · **Last updated:** Oct 12, 2026 · **Status:** Draft (v0.4)

> Markdown version of `API Client Framework – Design Doc.docx`, kept in the repo
> so it renders on GitHub and Claude Code can read it. This file is now the
> source of truth.
>
> **Changes in v0.4:** added *Development environment and prerequisites*;
> code layout switched to a `src/` layout and now shows the full GitHub repo
> structure.

## Summary

I'm building a small Python library for pulling data out of HTTP APIs reliably.
It takes care of the boring-but-hard parts (retries, pagination, provider rate
limits, auth, proxies) so that an ingestion job is mostly config plus a few
lines of code.

The interesting part, and the reason this isn't just another HTTP wrapper, is
quota handling: hourly and daily limits that survive restarts, can be shared
between workers, and eventually support large parallel backfills. Loading data
into a warehouse or lake is out of scope; for that I plan to hand off to dlt.

## Background

Jobs that pull from SaaS and public APIs tend to break in the same few ways. A
provider returns 429s or 503s and the job dies instead of backing off. A daily
quota runs out halfway through a backfill and nobody notices until the next
morning. A crash at page 4,000 means starting again from page 1. Each team ends
up writing its own retry loop and its own pagination code, slightly differently
each time.

There are good tools nearby (httpx for HTTP, dlt and Airbyte for loading), but
none of them treat provider quotas as a first-class problem. I want a single,
well-tested layer for that, which I can reuse across projects and later grow
into an end-to-end pipeline.

## Goals and non-goals

For v1 the library should:

- Support GET, POST, PUT, PATCH, DELETE and HEAD through one code path.
- Handle the common pagination styles out of the box.
- Retry automatically, but only where a retry can actually succeed.
- Respect per-second limits and hourly/daily quotas.
- Be configurable (APIs, auth, forward proxy) from YAML or plain Python.
- Stay small. Two required dependencies, httpx and pydantic; everything else optional.

Things I'm deliberately not doing yet: parallel sharding (designed for, not
built), gRPC and WebSockets, storing response data, and anything that needs a
cloud account.

## Proposed design

The core is a client that pushes every request through a short chain of
middleware before it reaches httpx. Each concern lives in its own small class,
so it can be tested alone, swapped out, or reordered without touching the rest.

```
request ─▶ Logging ─▶ Retry ─▶ Auth ─▶ RateLimit ─▶ httpx transport ─▶ provider
```

### Request path

The order of the chain matters more than it looks. Retry sits outside auth and
the rate limiter, so a retried request picks up a fresh token and gets counted
against the quota like any other call. With the order flipped, retries would
quietly bypass the limiter.

Internally everything is async, with a thin sync wrapper on top. Async isn't
strictly needed for v1, but sharding later depends on it, and bolting async onto
a sync codebase afterwards is painful.

**Retries.** Only for responses where trying again can help: 408, 425, 429, 500,
502, 503, 504, plus connection errors and read timeouts. Other 4xx responses
fail immediately, since the request itself is wrong. Backoff is exponential with
full jitter (so many clients don't all retry at the same instant), and
Retry-After wins whenever the server sends it. GET, PUT, DELETE and HEAD retry
by default. POST and PATCH only retry if the caller opts in or sets an
Idempotency-Key, because a blind retry can create duplicate records.

**Pagination.** A strategy has two jobs: build the next request from the last
response, and pull the items out of a response. I'll ship offset/limit, page
number, cursor (located by JSON path), RFC 8288 Link headers and "next URL in
the body". Between them they cover the large majority of public APIs.
Strategies can change any part of the next request, including the body, which
is what GraphQL cursors need. Results come back as lazy `iter_pages()` /
`iter_items()` generators with optional resume checkpoints.

**Rate limits and quotas.** These turned out to be two different problems:

- Throughput limits (10 requests a second) are smoothed with a token bucket.
- Quota windows (5,000 an hour, 100,000 a day) are counters that need to survive
  restarts and sometimes be shared between processes.

When the provider sends `X-RateLimit-*` or `RateLimit-*` headers, those correct
the local counters, since the server is the source of truth. Some APIs charge
per query cost rather than per call, so a request can consume more than one
unit. When a quota runs out, the policy either sleeps until the window resets
(fine for a few seconds) or raises `QuotaExhausted` with the reset time (better
when the wait is hours).

### Auth, proxies and config

Auth types: none, API key (header or query string), bearer, basic, OAuth2 client
credentials, and a custom hook that takes any callable (handy for HMAC request
signing). The OAuth2 one caches its token, refreshes shortly before expiry, and
retries once on a 401. If several requests notice an expired token at the same
moment, only one of them refreshes it.

A forward proxy can be set per API or per endpoint, including SOCKS and a
`no_proxy` list. There's also a switch for whether to honour `HTTP(S)_PROXY`
from the environment. Corporate proxies often re-sign TLS, so custom CA bundles
and client certificates are supported from day one rather than as an
afterthought.

Config can be YAML or Python; both end up as the same Pydantic models. Secrets
never go in the file itself, only references like `${GITHUB_TOKEN}`, and the
loader complains if something looks like a pasted key. A typical API entry:

```yaml
defaults:
  timeout: {connect: 5, read: 30}
  retry: {max_attempts: 4, backoff_base: 0.5, max_backoff: 30}
  proxy: {url: "${HTTPS_PROXY}", no_proxy: ["localhost"]}

apis:
  github:
    base_url: https://api.github.com
    auth: {type: bearer, token: "${GITHUB_TOKEN}"}
    rate_limits:
      - {window: hour, limit: 5000, on_exhausted: raise}
    endpoints:
      list_repos:
        method: GET
        path: /users/{user}/repos
        pagination: {type: link_header, per_page: 100}
```

Nothing here assumes REST. Request and response bodies go through pluggable
codecs (JSON, form, XML, raw), and a small response classifier decides whether a
response is OK, retryable or a failure. That matters for GraphQL and JSON-RPC,
which happily return HTTP 200 with an error in the body.

### State, logging and errors

Only a few things need to outlive the process: quota counters (so a restart
doesn't reset a daily limit), OAuth tokens, pagination checkpoints, and
optionally ETags for conditional requests. They sit behind a tiny `StateStore`
interface with three implementations: in-memory (the default), SQLite (one
machine, no extra dependency) and Redis (several workers sharing one quota). I'm
intentionally not storing response data.

Logging uses the standard logging module under an `apiframework` logger, and the
library never configures handlers itself, since that's the application's
decision. Each record has the method, the URL template rather than the
filled-in URL (lower cardinality, no leaked IDs), status, latency, attempt
number and remaining quota. Auth headers, cookies and API keys are redacted by
default; bodies are only logged at DEBUG and only if you ask. Hooks
(`on_request`, `on_retry`, `on_rate_limited` and so on) are there for anyone who
wants metrics, and OpenTelemetry is an optional extra.

Errors form a small hierarchy under `ApiError`: `HTTPStatusError` (which carries
the response), `RetryExhausted`, `QuotaExhausted`, `AuthError` and
`ConfigError`. Timeouts are always on, and there are no module-level globals, so
two clients in one process never interfere.

### Repository and code layout

The project lives in a GitHub repo
([nileshmevadagit/API_framework](https://github.com/nileshmevadagit/API_framework)).
The repo is named `API_framework`; the importable package is `apiframework`.
Code uses a `src/` layout so tests always run against the installed package,
not whatever happens to be on the path.

```
API_framework/
├── .github/
│   ├── workflows/ci.yml          # lint, mypy, unit tests on 3.10–3.13
│   ├── workflows/nightly.yml     # integration tests (docker + public APIs)
│   └── ISSUE_TEMPLATE/  pull_request_template.md  dependabot.yml
├── .vscode/                      # settings.json, extensions.json, launch.json
├── design_doc/                   # this document (+ original .docx)
├── src/apiframework/
│   ├── client.py  config.py  endpoints.py  errors.py  cli.py
│   ├── middleware/               # logging, retry, auth, ratelimit
│   ├── auth/                     # api_key, bearer, basic, oauth2, custom
│   ├── pagination/               # offset, page, cursor, link_header, next_url
│   ├── codecs/                   # json, form, xml, raw
│   ├── state/                    # memory, sqlite, redis
│   └── adapters/dlt.py           # optional extra
├── tests/unit/  tests/integration/  examples/
├── CLAUDE.md  README.md  CONTRIBUTING.md  CHANGELOG.md  LICENSE
├── pyproject.toml  uv.lock  .python-version
├── docker-compose.yml  .env.example
└── .pre-commit-config.yaml  .editorconfig  .gitignore  .gitattributes
```

A `Dockerfile` joins the root when the CLI runner milestone lands.

## Development environment and prerequisites

The full, step-by-step setup lives in the README
([Prerequisites](../README.md#prerequisites) and
[Getting started](../README.md#getting-started)); this section records the
decisions behind it.

**Primary environment.** macOS on Apple Silicon, VS Code, and Claude Code used
through its VS Code extension. Linux works unchanged; Windows contributors use
WSL 2. Everything has to run natively on arm64, which is why the local httpbin
is the multi-arch Go port (`ghcr.io/mccutchen/go-httpbin`) rather than the
original amd64-only image.

**Required tools.**

| Tool | Version | Role |
| --- | --- | --- |
| Git | 2.40+ | version control; GitHub hosts the repo and CI |
| uv | 0.8+ | installs Python, creates `.venv`, resolves and locks deps |
| Python | 3.10–3.13 | supported range; dev pinned to 3.12 via `.python-version`, installed by uv |
| VS Code | 1.94+ | editor; 1.94 is the Claude Code extension's minimum |
| Claude Code extension | latest | `anthropic.claude-code`; needs a paid Claude plan or a Console account |

**Optional tools.** Docker Desktop (or OrbStack/Colima) for the integration
services in `docker-compose.yml`; GitHub CLI; a no-scope GitHub token in `.env`
for higher GitHub API limits in integration tests. No cloud account is needed
until Stage 2.

**Why uv.** One tool replaces pyenv, venv, pip and pip-tools, and the committed
`uv.lock` makes CI and every laptop resolve identical versions. Contributors
never install Python by hand, and a conda base environment shouldn't be active
in the project shell.

**Why these VS Code settings are committed.** `.vscode/settings.json` points the
interpreter at `.venv`, formats with Ruff on save and runs pytest from the
Testing panel, so every contributor gets the same behaviour.
`.vscode/extensions.json` recommends the extensions that make that work.

**Claude Code conventions.** `CLAUDE.md` at the repo root is the shared brief
(commands, architecture invariants, testing rules) and is committed. All other
Claude Code files — `.claude/` (permissions, skills), `CLAUDE.local.md`,
`.mcp.json` — are personal and git-ignored, so the repo carries no tool-specific
clutter beyond that one file.

**Quality gates.** The same checks run in three places: pre-commit (ruff,
mypy), CI on every push and PR (ruff, format check, mypy, pytest on 3.10–3.13),
and nightly (integration tests against docker-compose and public APIs).

## Alternatives considered

**requests instead of httpx.** requests is more familiar, but it's sync-only and
I'd have to build async and HTTP/2 support myself. httpx gives sync and async
with one API, plus proxies and fine-grained timeouts.

**Using tenacity for retries.** It would work, and it's a reasonable fallback.
I'd still rather own the roughly 100 lines of retry logic, because retries have
to cooperate with the quota limiter, the idempotency rules and the response
classifier, and keeping that visible makes it easier to reason about.

**Building on an existing data tool.** I looked at the three obvious candidates:

| Tool | Licence | Good at | Why I'm not building on it |
| --- | --- | --- | --- |
| dlt | Apache 2.0 | Loading, schema evolution, incremental state, many destinations | It already ships its own REST client, so a plugin would mostly duplicate it. I'll use dlt for loading via an adapter instead. |
| Airbyte | Elastic License 2.0 (source-available) | Large connector catalogue, UI, managed cloud | It's a platform to operate, and its connector kit ties the work to Airbyte's protocol. |
| Singer / Meltano | Open spec / MIT | Reusing community taps | Each tap implements retries and limits its own way; I want one consistent layer. |

The split I settled on: build the extraction side (retries, quotas, pagination,
checkpoints, later sharding) myself, and hand records to dlt through an optional
`apiframework[dlt]` adapter for everything after that. If a well-maintained
connector already exists for a source, that's usually the better choice than
this library.

## Testing

Most tests are unit tests with HTTP mocked by respx: every retry path,
Retry-After parsing in both formats, quota window rollover, each pagination
strategy. The clock is injected rather than slept on, so a test of a daily
window runs in milliseconds.

Integration tests run against free public APIs, chosen because each one
exercises something specific:

- JSONPlaceholder for the full set of HTTP verbs.
- httpbin for forced status codes (503, 429), slow responses, basic and bearer
  auth, and checking what headers actually went out.
- GitHub's REST API for Link-header pagination and real rate-limit headers. Its
  low unauthenticated limit makes a good real-world quota test.
- PokéAPI for offset pagination with a next URL in the body.

Public APIs are flaky, so these are tagged `integration` and run nightly rather
than on every push. httpbin, Redis and mitmproxy also run locally through
docker-compose, which keeps CI stable and gives me a proxy to test against.

## Milestones and cost

v1 is free to build and run. Paid infrastructure only comes in later, and only
on purpose.

| Stage | What's in it | Cost |
| --- | --- | --- |
| 1 | The library, tests, public GitHub repo and Actions, docker-compose (httpbin, Redis, mitmproxy, MinIO, DynamoDB Local), local Kubernetes with kind | Free |
| 2 | A small AWS deployment: Lambda on an EventBridge schedule, S3, DynamoDB on-demand, SSM parameters, no VPC or NAT | A few dollars a month at most |
| 3 | Production scale: EKS, ElastiCache, Fargate, a managed orchestrator, NAT Gateway | Real ongoing cost |

To keep Stage 1 honest, cloud code only lives in optional extras like `[aws]`, a
stage setting points clients at local emulators or real AWS, and tests that cost
money have their own marker and never run in default CI. Before Stage 2 I'll set
up a budget alert, tag everything, and keep infrastructure in Terraform so it
can be torn down in one command.

Rough order of work:

0. Repo scaffold: packaging, tooling, CI, VS Code and Claude Code setup *(done)*
1. Config, client, transport (proxy, TLS)
2. Auth
3. Retries
4. Pagination
5. Rate limits with the in-memory store
6. SQLite and Redis stores
7. Hooks, JSON logs, OpenTelemetry extra
8. CLI runner, Dockerfile, docker-compose, dlt adapter
9. Docs and examples

After that, the plan is a reference pipeline: a public API (probably GitHub
events) through this library and dlt into Parquet/Iceberg on MinIO, then S3; dbt
for transformations, Dagster or Airflow for scheduling, data quality checks, and
a backfill benchmark (records, shards, quota used, failures recovered).

Tooling: uv, ruff, mypy --strict, pre-commit, GitHub Actions on Python 3.10 to
3.13, semantic versioning, Apache 2.0 licence.

## Future work

None of this is in v1, but the design leaves room for each piece so it can be
added as a new module rather than a rewrite.

**Parallel shards.** Some APIs let you split one big query into independent
ranges (by date, by ID, by region) and pull them in parallel. That isn't
pagination: each shard pages through its own results. The plan is a shard
planner that turns one query into a list of half-open ranges, and an executor
that runs them with a concurrency cap. All shards share one quota, each keeps
its own checkpoint so a failed run only retries what's missing, and a shard that
hits a provider's result cap gets split in two. To make this cheap later, v1
already treats requests as immutable specs that can be cloned with overrides,
keeps pagination state inside the iterator, and looks rate limiters up by key
instead of tying them to one client.

```yaml
sharding:
  planner: date_range
  param_start: created_after
  param_end: created_before
  range: {start: "2025-01-01", end: "2026-01-01", step: 7d}
  max_parallel: 8
  on_failure: collect
```

**Docker and Kubernetes.** The CLI runner (`apiframework run job.yaml`) goes into
a slim, non-root image. Config comes from ConfigMaps and Secrets, SIGTERM
triggers a checkpoint and a clean exit, and CronJobs handle schedules. Indexed
Jobs line up nicely with shards later, and the Redis store lets pods share a
quota.

**AWS.** Lambda plus EventBridge for small, frequent pulls; Fargate or Batch for
long backfills. A DynamoDB state store would cover serverless setups, secrets
would come from SSM or Secrets Manager through IAM roles, and a SigV4 auth plugin
would cover API Gateway.

**The full pipeline.** dlt handles loading; orchestration (Dagster, Airflow or
Step Functions) calls the runner, and checkpoints mean a retried task resumes
instead of starting over. Logs go to stdout as JSON for whatever the platform
collects.

Smaller ideas for later: a circuit breaker, typed responses via Pydantic models,
streaming and Server-Sent Events, and maybe a separate gRPC client that reuses
the retry and quota logic.

## Open questions

- [ ] Repo name, and public or private? → Name settled: `API_framework`. Visibility still open; public keeps GitHub Actions free.
- [ ] Ship the sync wrapper in v1, or async only at first?
- [ ] Will several processes share one quota soon? If so, the Redis store moves up the list.
- [ ] When sharding happens, will shards ever need different hosts or credentials, or only different parameters?
- [ ] Apache 2.0 or MIT? Leaning Apache for the patent grant. *(Scaffold ships Apache 2.0; easy to swap before the first release.)*
