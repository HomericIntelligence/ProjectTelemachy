# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Release workflow (`.github/workflows/release.yml`) that builds
  sdist+wheel on `v*.*.*` tag pushes, cross-checks the tag against
  `pyproject.toml` and `__init__.py`, attaches artifacts to a GitHub
  Release with changelog-derived notes, and publishes to PyPI via
  Trusted Publishing. Closes #153; part of #92.
- WorkflowExecutor: declarative YAML-driven multi-agent workflow orchestration
- AgamemnonClient: async HTTP client for ProjectAgamemnon REST API
- CLI: `run`, `plan`, `validate`, `status`, `list`, `cancel` commands
- Pydantic v2 models for workflow schema validation
- Docker and local runtime support for agent provisioning

### Changed (breaking)

- `REQUIRE_TLS` env var now defaults to `true` (was `false`). Closes #158.
  Telemachy will refuse to construct `AgamemnonClient` against plain `http://`
  Agamemnon URLs unless the operator explicitly sets `REQUIRE_TLS=false`.
  - Before: missing `REQUIRE_TLS` → silently allowed cleartext HTTP, transmitting
    the Bearer API key in the clear.
  - After: missing `REQUIRE_TLS` → `AgamemnonClient.__init__` raises
    `AgamemnonError` when `AGAMEMNON_URL` starts with `http://`. Set
    `REQUIRE_TLS=false` in your `.env` to opt back in for local dev — a
    `WARNING` is emitted at `Settings` construction time.

### Removed

- `NATS_URL` environment variable and `Settings.nats_url` configuration.
- `nats_url` keyword argument from `AgamemnonClient.__init__`.
- TLS-scheme validation for `nats://` URLs (no NATS code path remains).
  NATS event monitoring is tracked under issue #92; closes #40.
