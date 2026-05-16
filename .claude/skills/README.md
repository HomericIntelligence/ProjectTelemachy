# ProjectTelemachy Custom Skills

This directory holds repository-specific Claude / Hephaestus skills for
ProjectTelemachy-specific workflows. Skills are markdown documents that
describe **how to perform a recurring task** in this repository; they
complement the global Hephaestus skill library by capturing knowledge
that is too narrow for ecosystem-wide reuse.

## Conventions

- One skill per file: `<verb-noun>.md` (e.g., `validate-workflow.md`).
- Each skill begins with a one-line summary and a "Use when" trigger
  list, matching the Hephaestus skill format.
- Skills are executable as `Read`-and-follow procedures; they must not
  contain any side-effecting code that runs on load.
- New skills are reviewed in pull requests like any other change.

## Index

(Empty — see `docs/ROADMAP.md` for the first scheduled skill additions.)

## Suggested skills

These are tracked as work items and may live here once authored:

- `validate-workflow.md` — guided procedure for running
  `just validate` against a workflow YAML, including expected error
  shapes.
- `add-workflow-example.md` — procedure for adding a new workflow
  example under `workflows/`, with the Definition-of-Done checklist.
- `bump-version.md` — automation-friendly procedure walking through
  the three version sources of truth (`pyproject.toml`,
  `src/telemachy/__init__.py`, `CHANGELOG.md`).

## See also

- `~/.claude/skills/` — user-global skills.
- Hephaestus plugin skills enabled via `.claude/settings.json`.
- `docs/definition-of-done.md` — the standard a skill output must meet.
