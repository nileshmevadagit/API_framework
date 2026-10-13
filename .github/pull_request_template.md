## What and why

<!-- One or two sentences. Link the issue: Closes #123 -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest` (new behaviour has tests; bug fixes have a regression test)
- [ ] No new required dependency (or it's discussed in the issue)
- [ ] Design doc / README updated if behaviour or setup changed
