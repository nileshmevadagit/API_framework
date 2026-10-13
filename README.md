# API_framework

A small Python library (`apiframework`) for pulling data out of HTTP APIs
reliably. It handles the boring-but-hard parts — retries, pagination, provider
rate limits, auth, proxies — so an ingestion job is mostly config plus a few
lines of code. Its distinguishing feature is quota handling: hourly and daily
limits that survive restarts and can be shared between workers.

> **Status:** pre-alpha. The design is in
> [`design_doc/design.md`](design_doc/design.md); implementation is starting.

---

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
