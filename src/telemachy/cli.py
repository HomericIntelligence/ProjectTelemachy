"""Typer CLI for ProjectTelemachy."""

from __future__ import annotations

import asyncio
import logging
import re
import signal
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from telemachy.agamemnon_client import AgamemnonClient
from telemachy.config import settings
from telemachy.executor import WorkflowExecutor, run_workflow
from telemachy.models import WorkflowSpec

app = typer.Typer(
    name="telemachy",
    help="Declarative workflow engine for ProjectAgamemnon.",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging from settings (LOG_LEVEL env var, default INFO)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

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
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Simulate execution without calling Agamemnon")] = False,
) -> None:
    """Execute a workflow YAML file."""
    _validate_workflow_path(workflow_path)
    spec = _load_workflow(workflow_path)

    if dry_run:
        console.print(f"[bold yellow][dry-run][/bold yellow] Simulating workflow: {spec.name}")
        _print_plan(spec)
        state = asyncio.run(run_workflow(spec, dry_run=True))
        console.print(f"[bold yellow][dry-run][/bold yellow] Simulation complete. id={state.workflow_id}")
        return

    console.print(f"[bold green]Running workflow:[/bold green] {spec.name}")

    # Count total tasks across all teams for the progress display
    total_tasks = sum(len(team.tasks) for team in spec.teams)

    async def _run_with_signals() -> None:
        stop_event = asyncio.Event()
        completed_count = 0

        def _handle_signal(sig: int, _frame: object) -> None:
            logger.warning("Received signal %s, initiating graceful shutdown...", sig)
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task(
                f"Running workflow: {spec.name}  [Completed: 0/{total_tasks}]",
                total=None,
            )

            def _on_task_complete(**kwargs: object) -> None:
                nonlocal completed_count
                completed_count += 1
                task_info = kwargs.get("task", {})
                subject = task_info.get("subject", "?") if isinstance(task_info, dict) else "?"  # type: ignore[union-attr]
                progress.update(
                    task_id,
                    description=(
                        f"Running workflow: {spec.name}  "
                        f"[Completed: {completed_count}/{total_tasks}]  "
                        f"last: {subject}"
                    ),
                )

            async with AgamemnonClient(
                url=settings.agamemnon_url,
                api_key=settings.agamemnon_api_key,
                host_id=settings.host_id,
                require_tls=settings.require_tls,
                nats_url=settings.nats_url,
            ) as client:
                executor = WorkflowExecutor(client, stop_event=stop_event)
                executor.add_hook("on_task_complete", _on_task_complete)
                result = await executor.execute(spec)

        if result.status == "completed":
            console.print(f"[bold green]Workflow completed.[/bold green] id={result.workflow_id}")
        else:
            console.print(
                f"[bold red]Workflow {result.status}.[/bold red] "
                f"id={result.workflow_id}"
                + (f"  error={result.error}" if result.error else "")
            )
            raise typer.Exit(1)

    asyncio.run(_run_with_signals())


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


@app.command()
def schema(
    output: Path = typer.Option(
        Path("schemas/workflow-v1.json"),
        "--output", "-o",
        help="Path to write the JSON Schema file",
    ),
) -> None:
    """Export the workflow YAML JSON Schema for editor validation."""
    from telemachy.schema import write_workflow_schema
    output.parent.mkdir(parents=True, exist_ok=True)
    write_workflow_schema(output)
    typer.echo(f"Schema written to {output}")


def main() -> None:
    _setup_logging()
    app()


if __name__ == "__main__":
    main()
