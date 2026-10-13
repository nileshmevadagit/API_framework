# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Integration tests against JSONPlaceholder covering every HTTP verb, nested
  routes and the non-persisted write behaviour (`tests/integration/`, marker
  `integration`; base URL overridable with `JSONPLACEHOLDER_URL`).
- Project scaffold: packaging (uv + hatchling), ruff, mypy --strict, pytest,
  pre-commit, GitHub Actions (CI + nightly integration), docker-compose services,
  VS Code workspace settings, CLAUDE.md.
- Core types: `RequestSpec` (frozen, `clone()`), `Middleware` protocol, `Clock`
  protocol with `SystemClock`, `ApiError` hierarchy, `StateStore` protocol with
  an in-memory implementation and a shared contract test suite.
