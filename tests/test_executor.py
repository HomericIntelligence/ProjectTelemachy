"""Mock-based tests for WorkflowExecutor."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telemachy.executor import WorkflowExecutor
from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.models import AgentSpec, TaskSpec, WorkflowSpec


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
    client = MagicMock(spec=AgamemnonClient)
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
        await executor.execute(spec)

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

        async def fake_create_task(
            team_id: str,
            spec: TaskSpec,
            blocked_by_ids: list[str] | None = None,
            assignee_agent_id: str | None = None,
        ) -> str:
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


# ---------------------------------------------------------------------------
# Tests: error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_failed_dependency_skips_downstream_task(self) -> None:
        """When task A fails, task B (blocked_by A) must never be submitted."""
        # get_tasks returns A as "failed" after it is submitted, then stays failed
        get_tasks_responses = [
            # First poll (waiting for A to complete): A is still pending
            [{"subject": "Task A", "status": "pending"}],
            # Second poll: A has failed
            [{"subject": "Task A", "status": "failed"}],
            # Monitor phase: A is failed (will cause workflow to mark as failed)
            [{"subject": "Task A", "status": "failed"}],
        ]
        call_count: dict[str, int] = {"n": 0}

        async def fake_get_tasks(team_id: str) -> list[dict]:
            idx = min(call_count["n"], len(get_tasks_responses) - 1)
            call_count["n"] += 1
            return get_tasks_responses[idx]

        client = _make_mock_client()
        client.create_task = AsyncMock(return_value="task-id-001")
        client.get_tasks = AsyncMock(side_effect=fake_get_tasks)

        spec = _make_spec(
            tasks=[
                {"subject": "Task A", "description": "First task", "assign_to": "worker"},
                {
                    "subject": "Task B",
                    "description": "Blocked downstream task",
                    "assign_to": "worker",
                    "blocked_by": ["Task A"],
                },
            ],
            teardown="never",
        )

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        # Executor must complete (not hang)
        assert state.completed_at is not None

        # Task B must never have been submitted
        submitted_subjects = [
            call.args[1].subject
            for call in client.create_task.call_args_list
        ]
        assert "Task B" not in submitted_subjects
        assert "Task A" in submitted_subjects

    @pytest.mark.asyncio
    async def test_monitor_timeout_sets_failed_state(self) -> None:
        """When _monitor_completion raises asyncio.TimeoutError, workflow fails gracefully."""
        client = _make_mock_client()
        spec = _make_spec(teardown="never")

        executor = WorkflowExecutor(client, poll_interval=0.01)

        with patch.object(
            executor,
            "_monitor_completion",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError("monitor timed out"),
        ):
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.error is not None
        assert "timed out" in state.error

    @pytest.mark.asyncio
    async def test_teardown_runs_even_when_execution_fails(self) -> None:
        """Teardown (delete_agent) must run even when the workflow raises mid-execution."""
        client = _make_mock_client()
        client.create_agent = AsyncMock(return_value="agent-to-teardown")
        spec = _make_spec(teardown="on_failure")

        executor = WorkflowExecutor(client, poll_interval=0.01)

        # Simulate an unexpected error during team/task creation phase
        with patch.object(
            executor,
            "_create_teams",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected mid-execution error"),
        ):
            state = await executor.execute(spec)

        # Workflow must be marked failed, not hanging
        assert state.status == "failed"
        # Teardown must still have run (policy=on_failure, status=failed → should delete)
        client.delete_agent.assert_called_once_with("agent-to-teardown")

    @pytest.mark.asyncio
    async def test_partial_agent_creation_teardown(self) -> None:
        """When second agent creation fails, already-created agents must be torn down."""
        client = _make_mock_client()

        # Agent 1 succeeds, agent 2 raises AgamemnonError
        client.create_agent = AsyncMock(
            side_effect=[
                "agent-id-first",
                AgamemnonError(500, "internal server error"),
            ]
        )

        spec = _make_spec(
            agents=[
                {"name": "agent-first", "runtime": "local"},
                {"name": "agent-second", "runtime": "local"},
            ],
            tasks=[
                {"subject": "T1", "description": "...", "assign_to": "agent-first"},
                {"subject": "T2", "description": "...", "assign_to": "agent-second"},
            ],
            teardown="on_failure",
        )

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        # Workflow must be marked failed due to the AgamemnonError
        assert state.status == "failed"
        assert state.error is not None

        # The first agent (which was created) must have been deleted during teardown
        deleted_ids = [call.args[0] for call in client.delete_agent.call_args_list]
        assert "agent-id-first" in deleted_ids
