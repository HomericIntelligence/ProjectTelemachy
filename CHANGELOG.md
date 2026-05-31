# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- WorkflowExecutor: declarative YAML-driven multi-agent workflow orchestration
- AgamemnonClient: async HTTP client for ProjectAgamemnon REST API
- CLI: `run`, `plan`, `validate`, `status`, `list`, `cancel` commands
- Pydantic v2 models for workflow schema validation
- NATS URL configuration (subscriber implementation pending)
- Docker and local runtime support for agent provisioning

### Changed (breaking)

- `REQUIRE_TLS` env var now defaults to `true` (was `false`). Closes #158; part of #92.
  Telemachy will refuse to construct `AgamemnonClient` against plain `http://` Agamemnon
  URLs or plain `nats://` NATS URLs unless the operator explicitly sets
  `REQUIRE_TLS=false`.
  - Before: missing `REQUIRE_TLS` → silently allowed cleartext HTTP, transmitting the
    Bearer API key in the clear.
  - After: missing `REQUIRE_TLS` → `AgamemnonClient.__init__` raises `AgamemnonError`
    when `AGAMEMNON_URL` starts with `http://` (or `NATS_URL` starts with `nats://`).
    Set `REQUIRE_TLS=false` in your `.env` to opt back in for local dev — a `WARNING`
    is emitted at `Settings` construction time.
