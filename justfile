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
        pixi run python -m telemachy.cli run "{{WORKFLOW}}"

# Dry-run: show what would be created without executing
plan WORKFLOW:
    AGAMEMNON_URL={{AGAMEMNON_URL}} NATS_URL={{NATS_URL}} \
        pixi run python -m telemachy.cli plan "{{WORKFLOW}}"

# Validate a workflow YAML without executing
validate WORKFLOW:
    pixi run python -m telemachy.cli validate "{{WORKFLOW}}"

# Export workflow JSON Schema for editor validation
schema:
    pixi run python -m telemachy.cli schema

# === Development ===

# Run the test suite
test:
    pixi run pytest

# Run ruff linter
lint:
    pixi run ruff check src tests

# Run mypy static type checker
mypy:
    pixi run mypy src/telemachy --ignore-missing-imports

# Format code with ruff
format:
    pixi run ruff format src tests

# Run the full local CI suite: lint, mypy, tests
check: lint mypy test

# Install dev dependencies and set up pre-commit hooks
bootstrap:
    pixi install
    pixi run pre-commit install
