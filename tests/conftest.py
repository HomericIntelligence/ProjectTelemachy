"""Shared test fixtures and factory helpers for Telemachy tests.

Addresses #149: replaces hardcoded YAML strings in test_models.py and
test_cli.py with a single set of typed factory functions. Each test calls
the factory with only the fields it cares about; defaults come from one
place so a schema change in src/telemachy/models.py only edits this file.

Also hosts the in-process Agamemnon stub fixtures used by the workflow
lifecycle integration tests (#146).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import yaml

from telemachy.agamemnon_client import AgamemnonClient
from telemachy.models import WorkflowSpec
from tests.stub_agamemnon import StubAgamemnon

# --- dict-level builders (single source of truth) --------------------------


def make_agent_dict(
    name: str = "worker",
    *,
    program: str = "claude-code",
    runtime: str = "local",
    docker_image: str | None = None,
    model: str | None = None,
    working_dir: str = "/tmp",
    cpus: int = 2,
    memory: str = "4g",
) -> dict[str, Any]:
    """Build a raw agent dict suitable for WorkflowSpec.model_validate.

    Always emits every key — no asymmetric omission of default values
    (review finding P7-1).
    """
    return {
        "name": name,
        "program": program,
        "runtime": runtime,
        "working_dir": working_dir,
        "model": model,
        "docker_image": docker_image,
        "cpus": cpus,
        "memory": memory,
    }


def make_task_dict(
    subject: str = "Do the thing",
    *,
    description: str = "Do something useful",
    assign_to: str = "worker",
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    """Build a raw task dict. blocked_by defaults to a freshly-allocated [] per call."""
    return {
        "subject": subject,
        "description": description,
        "assign_to": assign_to,
        "blocked_by": list(blocked_by) if blocked_by is not None else [],
    }


def make_team_dict(
    name: str = "team-a",
    *,
    agents: list[str] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a raw team dict. Defaults yield a one-agent / one-task team."""
    return {
        "name": name,
        "agents": list(agents) if agents is not None else ["worker"],
        "tasks": list(tasks) if tasks is not None else [make_task_dict()],
    }


def make_workflow_dict(
    *,
    name: str = "test-workflow",
    description: str = "A minimal test workflow",
    api_version: str = "telemachy/v1",
    agents: list[dict[str, Any]] | None = None,
    teams: list[dict[str, Any]] | None = None,
    teardown: str = "on_completion",
) -> dict[str, Any]:
    """Build a raw workflow dict. All defaults yield the canonical minimal workflow."""
    return {
        "apiVersion": api_version,
        "metadata": {"name": name, "description": description},
        "agents": list(agents) if agents is not None else [make_agent_dict()],
        "teams": list(teams) if teams is not None else [make_team_dict()],
        "teardown": teardown,
    }


# --- typed views over the dict builder -------------------------------------


def make_workflow_yaml(**overrides: Any) -> str:
    """Serialise the dict-form workflow to YAML text (for on-disk fixtures)."""
    return yaml.safe_dump(make_workflow_dict(**overrides), sort_keys=False)


def make_workflow_spec(**overrides: Any) -> WorkflowSpec:
    """Build a fully-validated WorkflowSpec."""
    return WorkflowSpec.model_validate(make_workflow_dict(**overrides))


def make_two_task_dep_dict() -> dict[str, Any]:
    """Canonical two-agent / one-dependency workflow used by dependency tests."""
    return make_workflow_dict(
        name="dep-workflow",
        description="Workflow with task dependency",
        agents=[make_agent_dict("agent-a"), make_agent_dict("agent-b")],
        teams=[
            make_team_dict(
                name="dep-team",
                agents=["agent-a", "agent-b"],
                tasks=[
                    make_task_dict("Step 1", description="First step", assign_to="agent-a"),
                    make_task_dict(
                        "Step 2",
                        description="Second step, depends on Step 1",
                        assign_to="agent-b",
                        blocked_by=["Step 1"],
                    ),
                ],
            )
        ],
    )


# --- pytest fixtures exposing the factories --------------------------------


@pytest.fixture()
def workflow_dict_factory() -> Callable[..., dict[str, Any]]:
    """Return make_workflow_dict so a test can build many variants."""
    return make_workflow_dict


@pytest.fixture()
def workflow_spec_factory() -> Callable[..., WorkflowSpec]:
    """Return make_workflow_spec so a test can build many validated specs."""
    return make_workflow_spec


@pytest.fixture()
def workflow_file_factory(tmp_path: Path) -> Callable[..., Path]:
    """Write a workflow YAML to tmp_path and return its Path."""

    def _make(filename: str = "workflow.yaml", **overrides: Any) -> Path:
        p = tmp_path / filename
        p.write_text(make_workflow_yaml(**overrides))
        return p

    return _make


# --- Agamemnon stub fixtures (integration / lifecycle tests, #146) ---------


def make_client_for(stub: StubAgamemnon) -> AgamemnonClient:
    """Sync builder: return an AgamemnonClient whose transport is *stub*'s ASGI app.

    NOT a fixture — call this from any test that needs a stub other than the
    default `stub_agamemnon`. The caller MUST register the client with the
    `client_pool` fixture so it is closed even if the test raises.
    """
    client = AgamemnonClient(url="http://stub", api_key="test-key", require_tls=False)
    client._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stub.asgi),
        base_url="http://stub",
        headers={"Content-Type": "application/json", "Authorization": "Bearer test-key"},
        timeout=5.0,
    )
    return client


@dataclass
class ClientPool:
    """Tracks every AgamemnonClient a test constructed so the fixture can close them."""

    _clients: list[AgamemnonClient] = field(default_factory=list)

    def register(self, client: AgamemnonClient) -> AgamemnonClient:
        self._clients.append(client)
        return client


@pytest_asyncio.fixture
async def client_pool() -> AsyncIterator[ClientPool]:
    """Async fixture that closes every registered client in its finally block.

    This is the ONLY lifetime-managing client fixture. It runs even when the
    test body raises, so transport sockets are always released.
    """
    pool = ClientPool()
    try:
        yield pool
    finally:
        for c in pool._clients:
            if c._client is not None:
                try:
                    await c._client.aclose()
                except Exception:
                    pass  # close is best-effort during teardown
                finally:
                    c._client = None


@pytest.fixture
def stub_agamemnon_factory() -> Callable[..., StubAgamemnon]:
    """Build a fresh StubAgamemnon, optionally preloaded with task→status sequences."""

    def _factory(task_statuses: dict[str, list[str]] | None = None) -> StubAgamemnon:
        return StubAgamemnon(task_statuses=task_statuses)

    return _factory


@pytest.fixture
def stub_agamemnon(stub_agamemnon_factory: Callable[..., StubAgamemnon]) -> StubAgamemnon:
    return stub_agamemnon_factory()


@pytest.fixture
def agamemnon_client(
    stub_agamemnon: StubAgamemnon, client_pool: ClientPool
) -> AgamemnonClient:
    """Default client bound to the default `stub_agamemnon` instance."""
    return client_pool.register(make_client_for(stub_agamemnon))


@pytest.fixture
def make_spec() -> Callable[..., WorkflowSpec]:
    """Factory producing WorkflowSpec instances parameterised by agents/tasks/teardown."""

    def _factory(
        agents: list[dict[str, Any]] | None = None,
        tasks: list[dict[str, Any]] | None = None,
        teardown: str = "on_completion",
        timeout_seconds: float | None = None,
    ) -> WorkflowSpec:
        agents = agents or [{"name": "worker", "runtime": "local"}]
        tasks = tasks or [{"subject": "Task 1", "description": "Do work", "assign_to": "worker"}]
        raw: dict[str, Any] = {
            "apiVersion": "telemachy/v1",
            "metadata": {"name": "lifecycle-test", "description": "integration"},
            "agents": agents,
            "teams": [
                {"name": "team-a", "agents": [a["name"] for a in agents], "tasks": tasks}
            ],
            "teardown": teardown,
        }
        if timeout_seconds is not None:
            raw["timeout_seconds"] = timeout_seconds
        return WorkflowSpec.model_validate(raw)

    return _factory


@pytest.fixture
def write_workflow_yaml(
    tmp_path: Path, make_spec: Callable[..., WorkflowSpec]
) -> Callable[..., Path]:
    """Persist a WorkflowSpec to a tmp YAML file and return its path."""

    def _writer(**kwargs: Any) -> Path:
        spec = make_spec(**kwargs)
        path = tmp_path / "workflow.yaml"
        path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False))
        return path

    return _writer


def load_workflow(path: Path) -> WorkflowSpec:
    """Single import point for the CLI's private _load_workflow."""
    from telemachy.cli import _load_workflow

    return _load_workflow(path)
