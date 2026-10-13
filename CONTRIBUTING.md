# Contributing

Setup and prerequisites are in the [README](README.md#prerequisites). This page
covers the day-to-day workflow.

## Workflow

1. Branch from `main`: `feat/retry-middleware`, `fix/retry-after-date`, `docs/...`.
2. Make the change with tests. Unit tests mock HTTP with `respx` and never sleep.
3. Run the gates (pre-commit runs most of them on commit):
   ```bash
   uv run ruff check . && uv run ruff format .
   uv run mypy
   uv run pytest
   ```
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat(retry): honour Retry-After HTTP-date`, `fix: ...`, `docs: ...`, `test: ...`.
5. Open a PR. CI must be green; the PR template has the checklist.

## Dependencies

- Runtime: only `httpx` and `pydantic`. Anything else goes in an optional extra
  in `pyproject.toml` and is imported lazily.
- Add dev tools with `uv add --dev <pkg>`; always commit the updated `uv.lock`.

## Where things go

| Change | Location |
| --- | --- |
| Library code | `src/apiframework/` |
| Unit tests | `tests/unit/` (mirror the source path) |
| Tests against real services | `tests/integration/`, marked `@pytest.mark.integration` |
| Runnable examples | `examples/` |
| Design decisions | `design_doc/design.md` |
| Release notes | `CHANGELOG.md` under *Unreleased* |

## Using Claude Code

`CLAUDE.md` is the shared brief for Claude Code and should stay accurate: if
you change an architecture rule, a command, or the layout, update it in the
same PR. Personal Claude Code files (`.claude/`, `CLAUDE.local.md`) are
git-ignored on purpose.
