# apiframework

A Python library for pulling data out of HTTP APIs reliably. It takes care of the
parts that usually break ingestion jobs: retries, pagination, provider rate limits,
auth, and proxies. Its distinguishing feature is quota handling: hourly and daily
limits are counted in a state store, so they survive restarts and can be shared
between workers.

Loading data is out of scope. Records come out as Python objects or JSON lines, and
an optional adapter hands them to [dlt](https://dlthub.com) for loading.

> **Status:** pre-alpha, version `0.0.1`. Everything below is implemented and tested,
> but the API may still change before a release. The design is in
> [`design_doc/design.md`](design_doc/design.md).

---

## Install

Not on PyPI yet. Install from a checkout:

```bash
pip install .                      # core: httpx and pydantic only
pip install ".[yaml,redis,otel]"   # with the optional extras you need
```

| Extra | Adds | Needed for |
| --- | --- | --- |
| `yaml` | PyYAML | job files and YAML config |
| `socks` | socksio | SOCKS proxies |
| `redis` | redis | the Redis state store |
| `otel` | opentelemetry-api | OpenTelemetry spans (`telemetry=True`) |
| `dlt` | dlt | the dlt adapter |

The `aws` extra is reserved for later work and nothing uses it yet.

---

## Quick start (Python)

```python
import asyncio

from apiframework.client import AsyncClient
from apiframework.config import parse_config
from apiframework.endpoints import build_request
from apiframework.pagination import PagePagination

config = parse_config(
    {
        "apis": {
            "jsonplaceholder": {
                "base_url": "https://jsonplaceholder.typicode.com",
                "endpoints": {
                    "posts": {
                        "method": "GET",
                        "path": "/posts",
                        "params": {"_limit": 10, "_page": 1},
                        "pagination": {"type": "page", "page_param": "_page"},
                    }
                },
            }
        }
    }
)


async def main() -> None:
    api = config.api("jsonplaceholder")
    async with AsyncClient(api) as client:
        spec = build_request(client, api.endpoints["posts"])
        async for post in client.iter_items(spec, PagePagination(page_param="_page")):
            print(post["id"], post["title"])


asyncio.run(main())
```

A blocking client with the same options is `apiframework.client.Client`. Don't use
it from inside a running event loop.

---

## Job files and the CLI

A job file defines APIs, their endpoints, and jobs. Each job runs one endpoint once,
to the end of its pagination, and writes one JSON object per line.

```yaml
# examples/jsonplaceholder-job.yaml
apis:
  jsonplaceholder:
    base_url: https://jsonplaceholder.typicode.com
    endpoints:
      posts:
        method: GET
        path: /posts
        params: {_limit: 10, _page: 1}
        pagination: {type: page, page_param: _page}

jobs:
  all_posts:
    api: jsonplaceholder
    endpoint: posts
    output: posts.jsonl   # omit to write to stdout
```

```bash
uv run apiframework run job.yaml                 # every job in the file
uv run apiframework run job.yaml --job all_posts # one job (repeatable)
uv run apiframework run job.yaml -vv             # log at DEBUG to stderr
python -m apiframework run job.yaml              # same thing, without the script
```

| Exit code | Meaning |
| --- | --- |
| `0` | every job finished |
| `1` | a job failed at runtime (HTTP error, retries exhausted, quota, I/O) |
| `2` | the job file or environment is wrong (missing job, invalid config, missing extra) |

A job's endpoint without `pagination` makes one request. A JSON list in the response
becomes one line per element; any other JSON value becomes one line.

Jobs are not scheduled. Run the CLI from cron, a Kubernetes CronJob, or an orchestrator
such as Dagster or Airflow. Each run starts from the beginning: there are no
incremental checkpoints yet.

### Docker

```bash
docker build -t apiframework:dev .
docker run --rm -v "$PWD/examples:/job:ro" apiframework:dev run /job/jsonplaceholder-job.yaml
```

The image runs as a non-root user and includes the `yaml`, `socks`, `redis` and `otel`
extras. It doesn't include `dlt`. A relative `output` path is written inside the
container, so mount a volume for it or write to stdout.

---

## Configuration reference

Every key below is checked on load. An unknown key is an error, so a typo fails
immediately.

```yaml
defaults:                 # shared by every API unless an API overrides the section
  timeout: {connect: 5, read: 30, write: 30, pool: 5}   # seconds, always set
  retry: {max_attempts: 4, backoff_base: 0.5, max_backoff: 30, retry_non_idempotent: false}
  proxy: {no_proxy: [localhost], trust_env: false}   # add url: "${HTTPS_PROXY}" when you have one
  tls: {verify: true, ca_bundle: null, client_cert: null, client_key: null}

apis:
  github:
    base_url: https://api.github.com
    headers: {Accept: application/vnd.github+json}
    auth: {type: bearer, token: "${GITHUB_TOKEN}"}   # needs GITHUB_TOKEN set in the environment
    rate_limits:
      - {window: hour, limit: 5000, on_exhausted: raise}
    endpoints:
      repos:
        method: GET
        path: /users/octocat/repos
        params: {per_page: 100}
        pagination: {type: link_header}

state:                    # where quota counters and tokens are kept
  type: sqlite            # memory (default) | sqlite | redis
  path: state.db          # sqlite: a file path; redis: url: "${REDIS_URL}" instead

observability:
  log_bodies: false       # bodies in DEBUG logs; off by default
  telemetry: false        # OpenTelemetry span per call (needs the otel extra)

jobs:
  repos:
    api: github
    endpoint: repos
    max_pages: 3
    output: repos.jsonl
```

### Secrets

Secrets are always references to environment variables. They are never written in the
file.

- A secret field (`token`, `password`, `client_secret`, `value`, `url` for Redis) must
  be `${NAME}`. Anything else is rejected.
- A header whose name looks like a credential (`Authorization`, `X-Api-Key`, names
  containing `key`, `token`, `secret`, `password` or `cookie`) must also be a reference.
- A value in a header or a URL that looks like a pasted key is rejected.
- A reference to a variable that is unset or empty is an error, and the error names the
  variable, never its value.
- Secrets are held as `SecretStr`, so they don't appear in `repr()` or logs.

### Endpoints

An endpoint is a method, a path, default params and headers, an optional pagination
rule, and a cost. Paths are used exactly as written. **Placeholders such as
`/users/{user}` are not filled in yet**, so write the full path, or set the part that
varies as a param.

### Auth

| `type` | Fields | Notes |
| --- | --- | --- |
| `none` | | the default |
| `bearer` | `token` | sends `Authorization: Bearer ...` |
| `basic` | `username`, `password` | sends `Authorization: Basic ...` |
| `api_key` | `name`, `value`, `location` (`header` or `query`) | |
| `oauth2` | `token_url`, `client_id`, `client_secret`, `scope`, `refresh_margin` | client credentials. The token is cached in the state store and refreshed `refresh_margin` seconds (default 60) before it expires. Concurrent requests share one refresh. A 401 drops the token and retries once. |

A custom signing function (for HMAC or SigV4) is possible from Python, through
`apiframework.auth.CustomAuth`. It can't be expressed in YAML.

### Retries

A response is retried when its status is 408, 425, 429, 500, 502, 503 or 504, or when
a connection fails or a read times out. Other 4xx responses fail immediately.

- Backoff is exponential with full jitter, between `backoff_base` and `max_backoff`.
- A `Retry-After` header always wins over backoff. Both forms are accepted: seconds
  and an HTTP date. It isn't capped, so a long `Retry-After` means a long wait.
- GET, HEAD, PUT and DELETE are retried. POST and PATCH are retried only when you set
  `retry_non_idempotent: true` or send an `Idempotency-Key` header.
- When the budget is spent, `RetryExhausted` is raised with the attempt count and the
  last error.

### Pagination

| `type` | Fields | Stops when |
| --- | --- | --- |
| `offset` | `limit`, `limit_param`, `offset_param`, `items_path` | a page is empty |
| `page` | `page_param`, `start`, `items_path` | a page is empty |
| `cursor` | `cursor_path`, `cursor_param`, `items_path` | the cursor is missing or empty |
| `has_more` | `more_path` (default `has_more`), `cursor_field` (default `id`), `cursor_param` (default `starting_after`), `items_path` | the flag is not `true`, or the page is empty |
| `link_header` | `rel` (default `next`) | there is no `rel="next"` link |
| `next_url` | `url_path`, `items_path` | the URL is missing or null |

`items_path` is a dotted path into the body, such as `data` or `results`. Leave it
empty when the body is the list. Relative next URLs are resolved against the request.
For `has_more`, the next cursor is `cursor_field` of the last record on the page.
If that record is not an object or lacks the field, `PaginationError` is raised.
If the server points back at a page already fetched, `PaginationError` is raised
instead of looping.

### Rate limits

- A per-second limit is a token bucket. A call waits until a token is free.
- An hour or day limit is a fixed window, aligned to the clock (for example, the top
  of the hour). It's counted in the state store. `on_exhausted: raise` (the default)
  raises `QuotaExhausted` with the reset time. `sleep` waits for the reset instead.
- For hour and day limits, server headers (`RateLimit-*` or `X-RateLimit-*`) correct the
  local count. A server that reports zero remaining blocks calls until its own reset time.
- Share one quota across clients by passing the same `RateLimiters` and state store.

### State stores

| `type` | Shared between | Notes |
| --- | --- | --- |
| `memory` | nothing | the default; lost on exit |
| `sqlite` | processes on one machine | WAL mode; increments are safe across processes |
| `redis` | machines | counters update atomically with a Lua script |

State holds quota counters, OAuth tokens and ETags. It never holds response data.

---

## Errors

Everything raised to you is an `ApiError`.

| Error | Raised when |
| --- | --- |
| `HTTPStatusError` | a response is a failure (for example 404), with the response attached |
| `RetryExhausted` | retries ran out, with the attempt count and last error |
| `ResponseRejected` | a 2xx response was rejected by your classifier (for example a GraphQL error in the body) |
| `QuotaExhausted` | an hour or day quota is used up, with the reset time |
| `AuthError` | credentials are missing, rejected, or a token request failed |
| `PaginationError` | pagination cannot continue safely |
| `ConfigError` | the configuration is invalid |

Non-JSON bodies are not handled yet. Reading a JSON response that isn't JSON raises
`json.JSONDecodeError`.

---

## Observability

- **Access log:** one record per call on the `apiframework.request` logger. It has the
  method, the URL template, the status, the latency, and the attempt count. The
  filled-in URL is never logged, so IDs stay out of the logs. Headers are logged only at
  DEBUG, after redaction. Bodies are logged only at DEBUG and only with `log_bodies`.
- **Hooks:** pass `Hooks(on_request=..., on_response=..., on_retry=..., on_rate_limited=...)`
  to a client. A hook that raises is logged and skipped.
- **JSON logs:** `apiframework.logging_json.JsonFormatter` writes each record as one
  JSON object. Attach it to a handler in your application. The library never configures
  logging itself.
- **OpenTelemetry:** `telemetry=True` starts a span per call. It needs the `otel` extra.
  No SDK is configured for you.

The CLI turns on logging to stderr and reads `observability:` from the job file. From
Python, you pass these options to the client.

---

## Limitations (v0.0.1)

- JSON only. XML, form and raw bodies aren't supported.
- Path placeholders (`/users/{user}`) aren't filled in.
- No incremental runs or checkpoints. Each run starts from the beginning.
- Rate limits are per API, not per endpoint.
- The remaining quota isn't in the access log yet.
- The CLI doesn't catch non-JSON responses, so one produces a traceback instead of exit
  code 1.
- No sharding and no parallel requests within a job.

## Examples

Each example runs with `uv run python examples/<name>.py`, and needs internet access.

- [`examples/jsonplaceholder_crud.py`](examples/jsonplaceholder_crud.py): every HTTP verb, and the fact that writes are not stored
- [`examples/github_repos.py`](examples/github_repos.py): Link-header pagination and rate-limit headers (set `GITHUB_TOKEN` for a higher limit)
- [`examples/pokeapi_offset.py`](examples/pokeapi_offset.py): pagination with a next URL in the body
- [`examples/hooks_and_json_logs.py`](examples/hooks_and_json_logs.py): hooks and JSON log lines
- [`examples/jsonplaceholder-job.yaml`](examples/jsonplaceholder-job.yaml): a complete job file for the CLI

---

# Development

## Prerequisites

The primary development setup is **macOS on Apple Silicon** with **VS Code**
and **Claude Code in VS Code**. Linux works the same way; Windows contributors
should use WSL 2.

### Required

| Tool | Version | Why | Install (macOS) | Check |
| --- | --- | --- | --- | --- |
| Homebrew | any | installs everything below | see [brew.sh](https://brew.sh) | `brew --version` |
| Git | 2.40+ | version control | `brew install git` | `git --version` |
| uv | 0.8+ | Python versions, venv, deps, lockfile | `brew install uv` | `uv --version` |
| Python | 3.10–3.13 | runtime | **installed by uv** (`.python-version` pins 3.12 for dev) | `uv run python --version` |
| VS Code | 1.94+ | editor (Claude Code extension needs ≥ 1.94) | `brew install --cask visual-studio-code` | `code --version` |

You don't need to install Python yourself or touch Anaconda/conda: uv
downloads the right interpreter and creates `.venv/` in the repo. If a conda
environment auto-activates in your shell, run `conda deactivate` before working
here (or `conda config --set auto_activate_base false`) so it doesn't shadow
the project venv.

To get the `code` command on your PATH: open VS Code → Command Palette
(`Cmd+Shift+P`) → **Shell Command: Install 'code' command in PATH**.

### Claude Code in VS Code

| Item | Details |
| --- | --- |
| Account | A paid Claude plan (Pro, Max, Team or Enterprise) or a Claude Console account. The free plan doesn't include Claude Code. No API key needed. |
| Extension | **Claude Code** by Anthropic (`anthropic.claude-code`). It's in this repo's recommended extensions, so VS Code offers it when you open the folder, or install it from the Extensions view (`Cmd+Shift+X`). |
| CLI (optional) | The extension bundles its own copy. Install the standalone CLI only if you also want `claude` in the integrated terminal: `curl -fsSL https://claude.ai/install.sh \| bash` (or `brew install --cask claude-code`). Check with `claude --version`. |

Claude Code reads [`CLAUDE.md`](CLAUDE.md) automatically: it's the project brief
(commands, architecture rules, conventions). Personal Claude Code settings live
in `.claude/` and are git-ignored.

### Optional (needed for integration tests)

| Tool | Why | Install (macOS) |
| --- | --- | --- |
| Docker Desktop (or OrbStack / Colima) | runs httpbin, Redis and mitmproxy from `docker-compose.yml` | `brew install --cask docker` |
| GitHub CLI | PRs and CI status from the terminal | `brew install gh` |
| GitHub token | raises GitHub's API limit for integration tests (60 → 5,000 req/hour) | put in `.env` as `GITHUB_TOKEN` (no scopes needed) |

Nothing in this project needs a cloud account or costs money to develop.

### VS Code extensions

Opening the folder prompts **"Install recommended extensions"**; accept it.
The list is in [`.vscode/extensions.json`](.vscode/extensions.json): Claude
Code, Python + Pylance + debugger, Ruff, Mypy, Even Better TOML, YAML, GitHub
Actions, Docker, EditorConfig.

---

## Getting started

```bash
# 1. Clone (skip if you already have the folder)
git clone https://github.com/nileshmevadagit/API_framework.git
cd API_framework

# 2. Create .venv with Python 3.12 and install all dev dependencies
uv sync

# 3. Git hooks: ruff + mypy run on every commit
uv run pre-commit install

# 4. Secrets template
cp .env.example .env

# 5. Open in VS Code
code .
```

Then in VS Code:

1. Accept **Install recommended extensions**.
2. Check the interpreter is `.venv` (bottom-right status bar; or `Cmd+Shift+P` →
   **Python: Select Interpreter** → `./.venv/bin/python`).
3. Open any file and click the **Claude Code** (spark) icon in the editor's top
   right, then sign in the first time.

### Verify everything works

```bash
uv run ruff check .        # lint
uv run mypy                # type-check (strict)
uv run pytest              # unit tests — no network, no Docker needed
```

Integration tests (optional):

```bash
docker compose up -d       # httpbin :8080, redis :6379, mitmproxy :8888 (UI :8081)
uv run pytest -m integration
docker compose down
```

---

## Repository layout

```
API_framework/
├── .github/
│   ├── workflows/ci.yml        # lint, mypy, tests on Python 3.10–3.13
│   ├── workflows/nightly.yml   # integration tests against docker + public APIs
│   ├── ISSUE_TEMPLATE/  pull_request_template.md  dependabot.yml
├── .vscode/                    # shared settings, recommended extensions, debug configs
├── design_doc/
│   ├── design.md               # design doc (source of truth, renders on GitHub)
│   └── API Client Framework – Design Doc.docx   # original Word version
├── src/apiframework/           # the library (src layout)
├── tests/
│   ├── unit/                   # fast, mocked with respx — run on every push
│   └── integration/            # real services, marked `integration`
├── examples/
├── CLAUDE.md                   # brief for Claude Code
├── CONTRIBUTING.md  CHANGELOG.md  LICENSE
├── docker-compose.yml  .env.example
├── pyproject.toml  uv.lock  .python-version
└── .pre-commit-config.yaml  .editorconfig  .gitignore  .gitattributes
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE).
