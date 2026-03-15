# ProjectTelemachy

A declarative workflow engine for [ai-maestro](https://github.com/HomericIntelligence/ai-maestro). Define multi-agent workflows in YAML — Telemachy handles provisioning, task orchestration, event monitoring, and teardown via the ai-maestro REST API.

## Overview

Telemachy reads a workflow YAML file, creates agents and teams through ai-maestro, assigns tasks with dependency ordering, monitors task completion via NATS events, and tears down provisioned resources according to your policy.

No separate agent system is used. All execution is driven exclusively through ai-maestro.

## Quick Start

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your MAESTRO_URL and API key

# Run a workflow
just run workflows/example.yaml

# Dry-run: see what would be created
just plan workflows/example.yaml

# Validate a workflow file
just validate workflows/example.yaml

# Check status of a running workflow
just status <workflow-id>
```

## Workflow Schema

A workflow YAML has four top-level sections:

```yaml
apiVersion: telemachy/v1

metadata:
  name: my-workflow
  description: "What this workflow does"

agents:
  - name: researcher
    program: claude-code
    model: claude-opus-4-5
    working_dir: /workspace
    runtime: local          # local | docker

  - name: coder
    program: claude-code
    runtime: docker
    docker_image: ghcr.io/homericintelligence/achaeanfleet:latest
    cpus: 4
    memory: 8g

teams:
  - name: core-team
    agents:
      - researcher
      - coder
    tasks:
      - title: "Research the domain"
        description: "Investigate the problem space and summarize findings."
        assign_to: researcher

      - title: "Implement solution"
        description: "Based on research findings, implement the solution."
        assign_to: coder
        depends_on:
          - "Research the domain"

teardown: on_completion   # on_completion | on_failure | never
```

### Agent Fields

| Field | Default | Description |
|---|---|---|
| `name` | required | Unique name within workflow |
| `program` | `claude-code` | Agent program to run |
| `model` | null | Override model (e.g. `claude-opus-4-5`) |
| `working_dir` | `/tmp` | Agent working directory |
| `runtime` | `local` | `local` or `docker` |
| `docker_image` | null | Required when `runtime: docker` |
| `cpus` | `2` | CPU allocation (docker only) |
| `memory` | `4g` | Memory allocation (docker only) |

### Teardown Policies

- `on_completion` — delete all agents and teams when all tasks succeed
- `on_failure` — delete only on failure (preserve state on success for inspection)
- `never` — never auto-teardown; manual cleanup required

## Development

```bash
just test      # run tests
just lint      # ruff check
just format    # ruff format
```
