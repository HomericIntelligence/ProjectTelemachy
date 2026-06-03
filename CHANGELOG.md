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
- NATS URL configuration (subscriber implementation pending)
- Docker and local runtime support for agent provisioning
