# === Variables ===

AGAMEMNON_URL := env_var_or_default("AGAMEMNON_URL", "http://localhost:8080")
NATS_URL      := env_var_or_default("NATS_URL", "nats://localhost:4222")

# === Default ===

default:
    @just --list

# === Workflow Execution ===

# Execute a workflow YAML file
run WORKFLOW:
    AGAMEMNON_URL={{AGAMEMNON_URL}} NATS_URL={{NATS_URL}} \
        pixi run python -m telemachy.cli run {{WORKFLOW}}

# Dry-run: show what would be created without executing
plan WORKFLOW:
    AGAMEMNON_URL={{AGAMEMNON_URL}} NATS_URL={{NATS_URL}} \
        pixi run python -m telemachy.cli plan {{WORKFLOW}}

# Show status of a running workflow
status WORKFLOW_ID:
    AGAMEMNON_URL={{AGAMEMNON_URL}} \
        pixi run python -m telemachy.cli status {{WORKFLOW_ID}}

# List all workflows (running and completed)
list:
    AGAMEMNON_URL={{AGAMEMNON_URL}} \
        pixi run python -m telemachy.cli list

# Cancel a running workflow
cancel WORKFLOW_ID:
    AGAMEMNON_URL={{AGAMEMNON_URL}} \
        pixi run python -m telemachy.cli cancel {{WORKFLOW_ID}}

# Validate a workflow YAML without executing
validate WORKFLOW:
    pixi run python -m telemachy.cli validate {{WORKFLOW}}

# === Development ===

# Run the test suite
test:
    pixi run pytest

# Run ruff linter
lint:
    pixi run ruff check src tests

# Format code with ruff
format:
    pixi run ruff format src tests
