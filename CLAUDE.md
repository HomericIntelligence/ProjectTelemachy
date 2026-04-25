# ProjectTelemachy — CLAUDE.md

## Project Overview

ProjectTelemachy is a declarative workflow engine that automates multi-agent workflows by calling the ProjectAgamemnon REST API. Users define workflows in YAML; Telemachy parses them, provisions agents and teams via Agamemnon, assigns tasks with dependency ordering, monitors execution via NATS events, and tears down resources according to the workflow's teardown policy.

**This project uses ProjectAgamemnon exclusively as its execution backend.** There is no parallel agent system — all agent lifecycle management flows through Agamemnon's REST API.

## Architecture

```
Workflow YAML
    │
    ▼
WorkflowSpec (Pydantic)
    │
    ▼
WorkflowExecutor
    ├── AgamemnonClient  →  POST /v1/agents              (create agents)
    ├── AgamemnonClient  →  POST /v1/agents/{id}/start   (start agents)
    ├── AgamemnonClient  →  POST /v1/teams               (create teams)
    ├── AgamemnonClient  →  POST /v1/teams/{id}/tasks    (create tasks)
    ├── NATS subscriber  →  monitor task completion events
    └── AgamemnonClient  →  DELETE /v1/agents/{id}       (teardown)
```

### Key Components

- `telemachy/models.py` — Pydantic models for the workflow schema (AgentSpec, TaskSpec, TeamSpec, WorkflowSpec, WorkflowState)
- `telemachy/agamemnon_client.py` — Async HTTP client wrapping all ProjectAgamemnon REST endpoints used
- `telemachy/executor.py` — Orchestrates the full workflow lifecycle: provision → assign tasks → monitor → teardown
- `telemachy/cli.py` — Typer CLI (`run`, `plan`, `status`, `validate`, `list`, `cancel`)
- `telemachy/config.py` — Settings loaded from environment / `.env`

## Workflow Schema

```yaml
apiVersion: telemachy/v1
metadata:
  name: string
  description: string
agents:
  - name: string
    program: string          # default: claude-code
    model: string | null
    working_dir: string      # default: /tmp
    runtime: local | docker  # default: local
    docker_image: string | null
    cpus: int                # default: 2
    memory: string           # default: 4g
teams:
  - name: string
    agents: [string]         # references to agent names
    tasks:
      - subject: string
        description: string
        assign_to: string    # agent name
        blocked_by: [string] # task subjects
teardown: on_completion | on_failure | never
```

## Key Principles

1. **Declarative** — workflows describe desired state; Telemachy handles how to get there.
2. **Agamemnon exclusive** — never spawn agents directly; always call ProjectAgamemnon's REST API.
3. **Idempotent teardown** — teardown is always safe to re-run; errors are logged but do not block.
4. **Dependency-respecting** — tasks with `blocked_by` are not submitted until their predecessors complete.
5. **Observable** — all state transitions are logged; NATS events drive completion detection.
6. **Type-safe** — all Python code uses type hints; Pydantic validates all external data.

## Repository Structure

```
ProjectTelemachy/
├── src/
│   └── telemachy/
│       ├── __init__.py           # version
│       ├── cli.py                # Typer CLI entry point
│       ├── config.py             # Settings / env vars
│       ├── executor.py           # WorkflowExecutor
│       ├── agamemnon_client.py   # ProjectAgamemnon REST client
│       └── models.py             # Pydantic workflow models
├── workflows/
│   ├── example.yaml              # Simple 2-agent example
│   └── fleet-deploy.yaml         # Docker fleet example
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   └── test_executor.py
├── .env.example
├── CLAUDE.md
├── README.md
├── justfile
└── pixi.toml
```

## Development Guidelines

- All Python files must have type hints on all functions and class attributes.
- Use `async`/`await` throughout for I/O operations (HTTP, NATS).
- Use `httpx.AsyncClient` for all HTTP calls; never `requests`.
- Pydantic v2 models for all structured data.
- Errors from Agamemnon should raise typed exceptions, not generic ones.
- Tests use `pytest-asyncio` and mock the `AgamemnonClient` at the boundary.

## Common Commands

```bash
just run workflows/example.yaml    # execute a workflow
just plan workflows/example.yaml   # dry-run: print what would be created
just validate workflows/example.yaml  # validate YAML schema only
just status <workflow-id>          # show running workflow status
just list                          # list all workflows
just cancel <workflow-id>          # cancel a running workflow
just test                          # run pytest
just lint                          # ruff check
just format                        # ruff format
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGAMEMNON_URL` | `http://localhost:8080` | ProjectAgamemnon base URL |
| `AGAMEMNON_API_KEY` | `` | API key (if auth enabled) |
| `NATS_URL` | `nats://localhost:4222` | NATS server URL for event monitoring |
