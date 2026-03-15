"""Mock-based tests for WorkflowExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from telemachy.executor import WorkflowExecutor
from telemachy.maestro_client import MaestroClient
from telemachy.models import AgentSpec, TaskSpec, TeamSpec, WorkflowSpec, WorkflowState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_spec(
    agents: list[dict] | None = None,
    tasks: list[dict] | None = None,
    teardown: str = "on_completion",
) -> WorkflowSpec:
    agents = agents or [{"name": "worker", "runtime": "local"}]
    tasks = tasks or [
        {"subject": "Task 1", "description": "Do work", "assign_to": "worker"}
    ]
    return WorkflowSpec.model_validate(
        {
            "apiVersion": "telemachy/v1",
            "metadata": {"name": "test-wf", "description": "test"},
            "agents": agents,
            "teams": [
                {
                    "name": "team-a",
                    "agents": [a["name"] for a in agents],
                    "tasks": tasks,
                }
            ],
            "teardown": teardown,
        }
    )


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=MaestroClient)
    client.create_agent = AsyncMock(return_value="agent-id-001")
    client.wake_agent = AsyncMock()
    client.hibernate_agent = AsyncMock()
    client.delete_agent = AsyncMock()
    client.list_agents = AsyncMock(return_value=[])
    client.create_team = AsyncMock(return_value="team-id-001")
    client.create_task = AsyncMock(return_value="task-id-001")
    client.update_task = AsyncMock()
    client.get_tasks = AsyncMock(
        return_value=[{"subject": "Task 1", "status": "completed"}]
    )
    return client


# ---------------------------------------------------------------------------
# Tests: provisioning
# ---------------------------------------------------------------------------

class TestProvisioning:
    @pytest.mark.asyncio
    async def test_create_agent_called_for_each_agent(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(
            agents=[
                {"name": "agent-a", "runtime": "local"},
                {"name": "agent-b", "runtime": "local"},
            ],
            tasks=[
                {"subject": "T1", "description": "...", "assign_to": "agent-a"},
                {"subject": "T2", "description": "...", "assign_to": "agent-b"},
            ],
        )
        client.create_agent = AsyncMock(side_effect=["id-a", "id-b"])

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert client.create_agent.call_count == 2
        assert client.wake_agent.call_count == 2

    @pytest.mark.asyncio
    async def test_agent_ids_stored_in_state(self) -> None:
        client = _make_mock_client()
        client.create_agent = AsyncMock(return_value="maestro-xyz")
        spec = _make_spec()

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert "worker" in state.created_agents
        assert state.created_agents["worker"] == "maestro-xyz"

    @pytest.mark.asyncio
    async def test_correct_api_endpoint_for_docker_agent(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(
            agents=[
                {
                    "name": "worker",
                    "runtime": "docker",
                    "docker_image": "example/img:latest",
                }
            ]
        )
        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)

        # create_agent receives the AgentSpec; the client internally routes to docker endpoint
        call_args = client.create_agent.call_args[0][0]
        assert isinstance(call_args, AgentSpec)
        assert call_args.runtime == "docker"
        assert call_args.docker_image == "example/img:latest"


# ---------------------------------------------------------------------------
# Tests: team and task creation
# ---------------------------------------------------------------------------

class TestTaskCreation:
    @pytest.mark.asyncio
    async def test_create_team_called(self) -> None:
        client = _make_mock_client()
        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)
        client.create_team.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_called_for_each_task(self) -> None:
        client = _make_mock_client()
        client.get_tasks = AsyncMock(
            return_value=[
                {"subject": "T1", "status": "completed"},
                {"subject": "T2", "status": "completed"},
            ]
        )
        spec = _make_spec(
            tasks=[
                {"subject": "T1", "description": "...", "assign_to": "worker"},
                {"subject": "T2", "description": "...", "assign_to": "worker"},
            ]
        )
        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)
        assert client.create_task.call_count == 2

    @pytest.mark.asyncio
    async def test_dependent_task_submitted_after_predecessor(self) -> None:
        """Task with blocked_by must not be submitted before its dependency completes."""
        call_order: list[str] = []

        async def fake_create_task(team_id: str, spec: TaskSpec, blocked_by_ids: list[str] | None = None) -> str:
            call_order.append(spec.subject)
            return f"task-{len(call_order)}"

        # First call returns pending; second call returns completed
        get_tasks_responses = [
            [{"subject": "Step 1", "status": "pending"}],
            [{"subject": "Step 1", "status": "completed"}],
            [{"subject": "Step 1", "status": "completed"}, {"subject": "Step 2", "status": "completed"}],
        ]
        call_count = {"n": 0}

        async def fake_get_tasks(team_id: str) -> list[dict]:
            idx = min(call_count["n"], len(get_tasks_responses) - 1)
            call_count["n"] += 1
            return get_tasks_responses[idx]

        client = _make_mock_client()
        client.create_task = AsyncMock(side_effect=fake_create_task)
        client.get_tasks = AsyncMock(side_effect=fake_get_tasks)

        spec = _make_spec(
            tasks=[
                {"subject": "Step 1", "description": "...", "assign_to": "worker"},
                {
                    "subject": "Step 2",
                    "description": "...",
                    "assign_to": "worker",
                    "blocked_by": ["Step 1"],
                },
            ]
        )
        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)

        assert call_order[0] == "Step 1"
        assert call_order[1] == "Step 2"


# ---------------------------------------------------------------------------
# Tests: teardown
# ---------------------------------------------------------------------------

class TestTeardown:
    @pytest.mark.asyncio
    async def test_teardown_on_completion_deletes_agents(self) -> None:
        client = _make_mock_client()
        client.create_agent = AsyncMock(return_value="agent-to-delete")
        spec = _make_spec(teardown="on_completion")

        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)

        client.delete_agent.assert_called_once_with("agent-to-delete")

    @pytest.mark.asyncio
    async def test_teardown_never_skips_deletion(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(teardown="never")

        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)

        client.delete_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_on_failure_skips_on_success(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(teardown="on_failure")

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert state.status == "completed"
        client.delete_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_state_on_success(self) -> None:
        client = _make_mock_client()
        spec = _make_spec()

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert state.status == "completed"
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_failed_state_when_task_fails(self) -> None:
        client = _make_mock_client()
        client.get_tasks = AsyncMock(
            return_value=[{"subject": "Task 1", "status": "failed"}]
        )
        spec = _make_spec(teardown="never")

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.error is not None
