"""Typer CLI for ProjectTelemachy."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from telemachy.config import settings
from telemachy.executor import run_workflow
from telemachy.models import WorkflowSpec

app = typer.Typer(
    name="telemachy",
    help="Declarative workflow engine for ProjectAgamemnon.",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

_SHELL_METACHARACTERS: re.Pattern[str] = re.compile(r"[;&|$`><(){}\[\]!?*~\\]")


def _validate_workflow_path(path: Path) -> None:
    """Validate that *path* is safe to use as a workflow file path.

    Raises :class:`typer.BadParameter` if the path string contains shell
    metacharacters, or if the resolved path does not point to an existing file.
    """
    raw = str(path)
    if _SHELL_METACHARACTERS.search(raw):
        raise typer.BadParameter(
            f"Workflow path contains disallowed shell metacharacters: {raw!r}"
        )
    if not path.exists():
        raise typer.BadParameter(f"Workflow file not found: {raw!r}")
    if not path.is_file():
        raise typer.BadParameter(f"Workflow path is not a file: {raw!r}")


def _load_workflow(workflow_path: Path) -> WorkflowSpec:
    """Parse and validate a workflow YAML file into a WorkflowSpec."""
    if not workflow_path.exists():
        err_console.print(f"[red]File not found:[/red] {workflow_path}")
        raise typer.Exit(1)

    try:
        raw = yaml.safe_load(workflow_path.read_text())
    except yaml.YAMLError as exc:
        err_console.print(f"[red]YAML parse error:[/red] {exc}")
        raise typer.Exit(1)

    try:
        return WorkflowSpec.model_validate(raw)
    except Exception as exc:
        err_console.print(f"[red]Workflow schema error:[/red] {exc}")
        raise typer.Exit(1)


def _print_plan(spec: WorkflowSpec) -> None:
    """Print a human-readable plan of what would be created."""
    console.print(
        Panel(
            f"[bold]{spec.name}[/bold]\n{spec.description}",
            title="Workflow Plan",
            border_style="blue",
        )
    )

    # Agents table
    agent_table = Table(title="Agents to provision", show_header=True)
    agent_table.add_column("Name")
    agent_table.add_column("Program")
    agent_table.add_column("Runtime")
    agent_table.add_column("Image / Model")
    for agent in spec.agents:
        extra = agent.docker_image or agent.model or "-"
        agent_table.add_row(agent.name, agent.program, agent.runtime, extra)
    console.print(agent_table)

    # Tasks per team
    for team in spec.teams:
        task_table = Table(title=f"Team: {team.name} — tasks", show_header=True)
        task_table.add_column("Title")
        task_table.add_column("Assign to")
        task_table.add_column("Depends on")
        for task in team.tasks:
            task_table.add_row(
                task.subject,
                task.assign_to,
                ", ".join(task.blocked_by) or "-",
            )
        console.print(task_table)

    console.print(f"[dim]Teardown policy:[/dim] {spec.teardown}")


@app.command()
def run(
    workflow_path: Annotated[Path, typer.Argument(help=f"Path to workflow YAML file (default search dir: {settings.workflows_dir}, override with WORKFLOWS_DIR env var)")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print plan without executing")] = False,
) -> None:
    """Execute a workflow YAML file."""
    _validate_workflow_path(workflow_path)
    spec = _load_workflow(workflow_path)

    if dry_run:
        _print_plan(spec)
        return

    console.print(f"[bold green]Running workflow:[/bold green] {spec.name}")

    state = asyncio.run(run_workflow(spec))

    if state.status == "completed":
        console.print(f"[bold green]Workflow completed.[/bold green] id={state.workflow_id}")
    else:
        console.print(
            f"[bold red]Workflow {state.status}.[/bold red] "
            f"id={state.workflow_id}"
            + (f"  error={state.error}" if state.error else "")
        )
        raise typer.Exit(1)


@app.command()
def plan(
    workflow_path: Annotated[Path, typer.Argument(help="Path to workflow YAML file")],
) -> None:
    """Dry-run: print what would be created without executing."""
    _validate_workflow_path(workflow_path)
    spec = _load_workflow(workflow_path)
    _print_plan(spec)


@app.command()
def validate(
    workflow_path: Annotated[Path, typer.Argument(help=f"Path to workflow YAML file (default search dir: {settings.workflows_dir}, override with WORKFLOWS_DIR env var)")],
) -> None:
    """Validate a workflow YAML file against the Telemachy schema."""
    _validate_workflow_path(workflow_path)
    spec = _load_workflow(workflow_path)
    console.print(f"[bold green]Valid.[/bold green] Workflow: {spec.name}")


@app.command()
def status(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID returned by 'run'")],
) -> None:
    """Show the status of a running or completed workflow.

    Note: persistent state storage is not yet implemented.
    This command is a placeholder for future state backend integration.
    """
    console.print(
        f"[yellow]Status lookup for workflow '{workflow_id}' requires a state backend.[/yellow]\n"
        "Persistent workflow state storage is not yet implemented.\n"
        "Check ProjectAgamemnon directly for agent/team status."
    )


@app.command(name="list")
def list_workflows() -> None:
    """List all workflows (running and completed).

    Note: persistent state storage is not yet implemented.
    """
    console.print(
        "[yellow]Workflow listing requires a state backend.[/yellow]\n"
        "Persistent workflow state storage is not yet implemented."
    )


@app.command()
def cancel(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID to cancel")],
) -> None:
    """Cancel a running workflow.

    Note: cancellation via state backend is not yet implemented.
    """
    console.print(
        f"[yellow]Cancellation of workflow '{workflow_id}' requires a state backend.[/yellow]\n"
        "Persistent workflow state storage is not yet implemented."
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
