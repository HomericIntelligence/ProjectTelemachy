# ProjectTelemachy Roadmap

This roadmap is the authoritative planning artefact for ProjectTelemachy.
It captures **what is shipping now, what is shipping next, and what we
know is not yet built**. Every row links to an issue, an ADR, or both.

Conventions:
- Release lines follow `docs/backwards-compat.md` (SemVer; v0.x is pre-1.0).
- Each row links to a tracking issue (or notes _no issue yet_) and to
  any relevant ADR under `docs/adr/`.
- This file is regression-tested by `tests/test_roadmap.py`.

## Current Release (v0.1.x — Unreleased)

| Work | Status | Issue | ADR |
| --- | --- | --- | --- |
| HTTP-polling task monitoring | Shipped (default) | — | [ADR-001](adr/001-http-polling-monitoring.md) |
| Agamemnon-exclusive backend | Shipped | — | [ADR-002](adr/002-decouple-from-maestro.md) |
| Secure TLS default (`REQUIRE_TLS=true`) | Shipped | [#158](https://github.com/HomericIntelligence/ProjectTelemachy/issues/158) | — |
| Release workflow (PyPI + GH Release) | Shipped | [#153](https://github.com/HomericIntelligence/ProjectTelemachy/issues/153) | — |
| 75% coverage gate | Shipped | [#152](https://github.com/HomericIntelligence/ProjectTelemachy/issues/152) | — |
| Strict-audit remediation epic | In progress | [#92](https://github.com/HomericIntelligence/ProjectTelemachy/issues/92) | — |

## Next Release (v0.2.0)

| Work | Status | Issue | ADR |
| --- | --- | --- | --- |
| NATS subscriber for task-lifecycle events (supersedes ADR-001) | Planned | [#92](https://github.com/HomericIntelligence/ProjectTelemachy/issues/92) | ADR-001 → to be superseded |
| Roadmap & milestones (this artefact) | In progress | [#167](https://github.com/HomericIntelligence/ProjectTelemachy/issues/167) | [ADR-003](adr/003-roadmap-artifact.md) |

## Future (v1.0.0 and beyond)

| Work | Status | Issue | ADR |
| --- | --- | --- | --- |
| Persistent workflow-state backend (enables `status`/`list`/`cancel`) | Design not started | _no issue yet — file before starting work_ | _ADR required at design time_ |
| Stabilise workflow YAML to `apiVersion: telemachy/v1` (drop pre-1.0 caveats) | Pending v0.2.0 | _no issue yet_ | — |

## Known Limitations

- `status`, `list`, and `cancel` CLI commands are not implemented; they
  require the state backend listed in Future. Until then, query
  ProjectAgamemnon directly. (`CLAUDE.md` §Planned Features, `README.md`.)
- Task-completion detection is HTTP polling, bounded by
  `MONITOR_TIMEOUT_SECONDS` / `MONITOR_MAX_POLLS`. Event-driven
  detection is gated on the NATS subscriber above.
- `NATS_URL` is parsed and TLS-validated but **not yet subscribed to**;
  it is reserved for the planned subscriber.

## How to propose a roadmap change

1. Open an issue with label `roadmap`.
2. If the change implies an architectural decision, draft an ADR under
   `docs/adr/` per `docs/adr/template.md`.
3. Reference the issue + ADR from the relevant row in this file.
