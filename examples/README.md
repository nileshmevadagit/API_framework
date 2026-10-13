# Examples

Runnable examples land here as features are built, one per public API used in
the integration tests:

- `github_repos.py` — Link-header pagination and real rate-limit headers
- `pokeapi_offset.py` — offset pagination with a next URL in the body
- `jsonplaceholder_crud.py` — every HTTP verb through one client
- `job.yaml` — a complete YAML job for `apiframework run`

Each example must run with `uv run python examples/<name>.py` and nothing else.
