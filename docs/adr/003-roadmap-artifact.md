# ADR-003: `docs/ROADMAP.md` as the canonical planning artefact

- **Status:** Accepted
- **Date:** 2026-06-03
- **Deciders:** Telemachy maintainers
- **Context tags:** planning, governance, docs

## Context

Audit finding §10 (#167) observed that major outstanding work — the
NATS subscriber (#92) and the persistent state backend for `status` /
`list` / `cancel` — is referenced only in `CLAUDE.md` prose and a
`README.md` aside. There is no canonical planning artefact, no
milestones, and no roadmap labels. Future contributors have no
single place to read what is shipping, what is planned, and what is
not yet built.

## Decision

`docs/ROADMAP.md` is the canonical roadmap. It is:

1. Bound to GitHub Milestones (`v0.1.0`, `v0.2.0`, `v1.0.0`) so issues
   can be filtered by release line in the UI.
2. Tagged with the cross-cutting labels `roadmap`, `nats-subscriber`,
   and `state-backend`.
3. Regression-tested (`tests/test_roadmap.py`) for required H2
   sections and link integrity.
4. Linked from `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, and the
   PR template.

## Consequences

Positive:

- Single discoverable source for "what is planned".
- Drift surfaces as a CI failure rather than a stale prose snippet.
- ADRs and roadmap rows cross-reference each other.

Negative:

- Two places to update when planning changes: the roadmap row and the
  issue/ADR. Mitigated by the regression test, which fails if rows
  point at dead links.

## Alternatives considered

- **GitHub Projects only.** Rejected: not visible to anonymous readers,
  not version-controlled, not reviewable via PR.
- **Top-level `ROADMAP.md`.** Rejected: the PR template
  (`.github/pull_request_template.md:21`) already references
  `docs/ROADMAP.md`; planning artefacts already live under `docs/`.
- **Embed roadmap in `README.md`.** Rejected: would dilute the
  README's role as a quickstart and make the regression test brittle.

## References

- Issue #167, #92
- ADR-001, ADR-002
- `docs/backwards-compat.md`
