# Examples

Each Python example runs with `uv run python examples/<name>.py` and needs internet access.
Nothing needs a secret: `github_repos.py` uses `GITHUB_TOKEN` only when it's set.

- `jsonplaceholder_crud.py` — every HTTP verb through one client, and why created records can't be read back
- `github_repos.py` — Link-header pagination and rate-limit headers
- `pokeapi_offset.py` — pagination with a next URL in the body
- `hooks_and_json_logs.py` — metrics hooks and JSON log lines
- `jsonplaceholder-job.yaml` — a complete job file for `apiframework run`
  (`uv run apiframework run examples/jsonplaceholder-job.yaml`)
