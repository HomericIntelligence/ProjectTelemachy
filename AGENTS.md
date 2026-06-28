# AGENTS.md — ProjectTelemachy

This document specifies the multi-agent coordination protocols for
ProjectTelemachy within the HomericIntelligence distributed agent mesh.

## Role

ProjectTelemachy is the declarative workflow engine: it parses YAML
workflows, provisions agents and teams via ProjectAgamemnon's REST API,
assigns dependency-ordered tasks, monitors completion, and tears down
resources.

```
Workflow YAML
    │
    ▼
WorkflowSpec ──► WorkflowExecutor ──► ProjectAgamemnon REST API
                                     ▲
                                     └─ provisions agents/teams/tasks
```

Telemachy is the **only** agent authorised to translate declarative
workflow YAML into Agamemnon API calls. Other agents must not bypass
Telemachy to provision Agamemnon resources unless explicitly handing
off (see "Handoff" below).

## Role boundaries

| Agent | Owns | Must not do |
| --- | --- | --- |
| ProjectTelemachy | workflow YAML interpretation, dependency ordering, teardown policy | spawn agents directly (always via Agamemnon) |
| ProjectAgamemnon | agent / team / task lifecycle, HMAS orchestration | parse workflow YAML |
| ProjectNestor | research and ideation upstream | execute workflows |
| ProjectArgus | observability, log aggregation | mutate state in Agamemnon |
| ProjectHermes | Event bridge (NATS) | own agent lifecycle |

## Handoff contract

- **Inbound:** users (or ProjectNestor) deliver workflow YAML through the
  Typer CLI (`just run <file>`) or via library use of
  `telemachy.executor.WorkflowExecutor`.
- **Outbound:** Telemachy calls Agamemnon REST endpoints in the order
  documented in `CLAUDE.md`. The handoff payload to Agamemnon is the
  AgentSpec / TeamSpec / TaskSpec record validated by
  `telemachy.models`.

## Inter-agent message contracts

- All Agamemnon HTTP calls use `httpx.AsyncClient`; payloads conform to
  ProjectAgamemnon's published OpenAPI shape.
- Completion monitoring is performed by HTTP polling against the
  Agamemnon REST API. Future event-driven monitoring is tracked under
  issue #92.

## Coordination invariants

1. **Agamemnon exclusive.** Telemachy never spawns processes,
   containers, or agents itself.
2. **Dependency-respecting.** Tasks with `blocked_by` are not submitted
   until predecessors complete.
3. **Idempotent teardown.** Re-running teardown for an already-torn-down
   workflow is a no-op.
4. **Pure planning.** `just plan` and `just validate` never mutate
   Agamemnon state.

## See also

- `CLAUDE.md` — single-agent operational conventions and guardrails.
- `CONTRIBUTING.md` — contribution workflow.
