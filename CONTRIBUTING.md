# Contributing to ProjectTelemachy

Thank you for your interest in contributing to ProjectTelemachy! This is the workflow
execution engine for the [HomericIntelligence](https://github.com/HomericIntelligence)
distributed agent mesh — it runs, plans, monitors, and cancels named workflow YAML files
against Agamemnon and NATS.

For an overview of the full ecosystem, see the
[Odysseus](https://github.com/HomericIntelligence/Odysseus) meta-repo.

## Quick Links

- [Development Setup](#development-setup)
- [What You Can Contribute](#what-you-can-contribute)
- [Development Workflow](#development-workflow)
- [Building and Testing](#building-and-testing)
- [Pull Request Process](#pull-request-process)
- [Code Review](#code-review)

## Development Setup

### Prerequisites

- [Git](https://git-scm.com/)
- [GitHub CLI](https://cli.github.com/) (`gh`)
- [Pixi](https://pixi.sh/) for environment management (installs Python 3.10+)
- [Just](https://just.systems/) as the command runner

### Environment Setup

```bash
# Clone the repository
git clone https://github.com/HomericIntelligence/ProjectTelemachy.git
cd ProjectTelemachy

# Activate the Pixi environment
pixi shell

# Copy and customize environment variables
cp .env.example .env

# List available recipes
just --list
```

### Verify Your Setup

```bash
# Run tests
just test

# Validate an existing workflow
just validate <WORKFLOW>
```

## What You Can Contribute

- **Workflow steps** — New step types for the execution engine (`src/telemachy/`)
- **Workflow YAML definitions** — Reusable workflows in `workflows/`
- **Validation logic** — Schema validation and input checking improvements
- **Tests** — pytest test cases for engine logic and step execution
- **Justfile recipes** — New workflow management commands
- **Documentation** — README updates, workflow authoring guides

### Workflow YAML Format

Workflow definitions live in the `workflows/` directory. Reference existing workflows as
examples for the expected schema. Workflows define steps that execute against the
Agamemnon API and communicate over NATS subjects.

## Development Workflow

### 1. Find or Create an Issue

Before starting work:

- Browse [existing issues](https://github.com/HomericIntelligence/ProjectTelemachy/issues)
- Comment on an issue to claim it before starting work
- Create a new issue if one doesn't exist for your contribution

### 2. Branch Naming Convention

Create a feature branch from `main`:

```bash
git checkout main
git pull origin main
git checkout -b <issue-number>-<short-description>

# Examples:
git checkout -b 10-add-parallel-step-type
git checkout -b 7-fix-workflow-cancellation
```

**Branch naming rules:**

- Start with the issue number
- Use lowercase letters and hyphens
- Keep descriptions short but descriptive

### 3. Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**

| Type       | Description                |
|------------|----------------------------|
| `feat`     | New feature                |
| `fix`      | Bug fix                    |
| `docs`     | Documentation only         |
| `style`    | Formatting, no code change |
| `refactor` | Code restructuring         |
| `test`     | Adding/updating tests      |
| `chore`    | Maintenance tasks          |

**Example:**

```bash
git commit -m "feat(engine): add parallel step execution

Implements a 'parallel' step type that runs multiple child steps
concurrently with configurable concurrency limits.

Closes #10"
```

## Building and Testing

### Test

```bash
# Run all tests (pytest)
just test
```

### Lint and Format

```bash
# Run linter (ruff)
just lint

# Auto-format
just format
```

### Run Workflows

```bash
# Run a named workflow
just run <WORKFLOW>

# Preview execution plan (dry run)
just plan <WORKFLOW>

# Check workflow status
just status <WORKFLOW_ID>

# List all workflows
just list

# Cancel a running workflow
just cancel <WORKFLOW_ID>

# Validate workflow YAML
just validate <WORKFLOW>
```

### Python Conventions

- **Python version**: 3.10+ (managed by pixi)
- **Project layout**: src layout (`src/telemachy/`)
- **Build backend**: hatchling (`pyproject.toml`)
- **Type hints**: Required for all function parameters and return types
- **Linting/formatting**: ruff

## Pull Request Process

### Before You Start

1. Ensure an issue exists for your work
2. Create a branch from `main` using the naming convention
3. Implement your changes
4. Run `just test` and `just lint` to verify

### Creating Your Pull Request

```bash
git push -u origin <branch-name>
gh pr create --title "[Type] Brief description" --body "Closes #<issue-number>"
```

**PR Requirements:**

- PR must be linked to a GitHub issue
- PR title should be clear and descriptive
- Tests and linting must pass

### Never Push Directly to Main

The `main` branch is protected. All changes must go through pull requests.

## Code Review

### What Reviewers Look For

- **Workflow safety** — Are step inputs validated and sanitized?
- **Error handling** — Are failures handled gracefully with proper cleanup?
- **Test coverage** — Are new step types and engine logic tested?
- **No hardcoded secrets** — Are credentials in environment variables?
- **YAML schemas** — Do new workflow definitions conform to the schema?

### Responding to Review Comments

- Keep responses short (1 line preferred)
- Start with "Fixed -" to indicate resolution

## Markdown Standards

All documentation files must follow these standards:

- Code blocks must have a language tag (`python`, `bash`, `yaml`, `text`, etc.)
- Code blocks must be surrounded by blank lines
- Lists must be surrounded by blank lines
- Headings must be surrounded by blank lines

## Reporting Issues

### Bug Reports

Include: clear title, steps to reproduce, expected vs actual behavior, workflow YAML if relevant.

### Security Issues

**Do not open public issues for security vulnerabilities.**
See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

## Code of Conduct

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.

---

Thank you for contributing to ProjectTelemachy!
