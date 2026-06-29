"""Mock-based tests for WorkflowExecutor."""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.executor import WorkflowExecutor, WorkflowTimeoutError
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
    tasks = tasks or [{"subject": "Task 1", "description": "Do work", "assign_to": "worker"}]
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
    client.list_teams = AsyncMock(return_value=[])
    client.ping = AsyncMock(return_value=True)
    client.create_team = AsyncMock(return_value="team-id-001")
    client.create_task = AsyncMock(return_value="task-id-001")
    client.update_task = AsyncMock()
    client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "completed"}])
    client.delete_team = AsyncMock()
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
            [
                {"subject": "Step 1", "status": "completed"},
                {"subject": "Step 2", "status": "completed"},
            ],
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
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "failed"}])
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
        submitted_subjects = [call.args[1].subject for call in client.create_task.call_args_list]
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
            side_effect=TimeoutError("monitor timed out"),
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

    @pytest.mark.asyncio
    async def test_wake_agent_failure_still_records_created_agent_for_teardown(self) -> None:
        """If create_agent succeeds but wake_agent raises, the created agent
        must still appear in state.created_agents so teardown can delete it (#164).

        Single-agent case — no concurrency, ordering is trivial.
        """
        client = _make_mock_client()
        client.create_agent = AsyncMock(return_value="agent-created-but-not-woken")
        client.wake_agent = AsyncMock(side_effect=AgamemnonError(503, "service unavailable"))

        spec = _make_spec(
            agents=[{"name": "worker", "runtime": "local"}],
            teardown="on_failure",
        )

        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.created_agents.get("worker") == "agent-created-but-not-woken"
        deleted_ids = [call.args[0] for call in client.delete_agent.call_args_list]
        assert "agent-created-but-not-woken" in deleted_ids

    @pytest.mark.asyncio
    async def test_partial_provisioning_tracks_all_completed_creates_before_failure(
        self,
    ) -> None:
        """When create_agent fan-out has mixed outcomes, every agent whose
        create_agent returned an id must be present in state.created_agents,
        regardless of gather() completion ordering (#164).

        Determinism: max_concurrent_provisioning=1 forces the _bounded() coroutines
        to serialize through self._provision_semaphore. Calls to client.create_agent
        therefore arrive in agent-list order, so AsyncMock.side_effect entries map
        1:1 to agents A/B/C and the test does not depend on asyncio.gather
        scheduling behaviour.
        """
        client = _make_mock_client()
        client.create_agent = AsyncMock(
            side_effect=[
                "id-A",
                AgamemnonError(500, "boom"),
                "id-C",
            ]
        )

        spec = _make_spec(
            agents=[
                {"name": "agent-A", "runtime": "local"},
                {"name": "agent-B", "runtime": "local"},
                {"name": "agent-C", "runtime": "local"},
            ],
            tasks=[
                {"subject": "T", "description": "...", "assign_to": "agent-A"},
            ],
            teardown="on_failure",
        )

        # max_concurrent_provisioning=1 → strictly sequential create_agent calls.
        executor = WorkflowExecutor(client, poll_interval=0.01, max_concurrent_provisioning=1)
        state = await executor.execute(spec)

        assert state.status == "failed"
        # Every agent whose create_agent returned an id must be tracked,
        # even though one sibling raised mid-fan-out.
        assert state.created_agents.get("agent-A") == "id-A"
        assert state.created_agents.get("agent-C") == "id-C"
        assert "agent-B" not in state.created_agents
        # Both successfully-created agents must be torn down (delete_agent
        # ordering is not asserted — teardown iterates state.created_agents).
        deleted_ids = [call.args[0] for call in client.delete_agent.call_args_list]
        assert "id-A" in deleted_ids
        assert "id-C" in deleted_ids
        # wake_agent was called for both successful creates (default AsyncMock
        # succeeds), but not for the failing one.
        woken_ids = [call.args[0] for call in client.wake_agent.call_args_list]
        assert "id-A" in woken_ids
        assert "id-C" in woken_ids


# ---------------------------------------------------------------------------
# Tests: hooks (#144)
# ---------------------------------------------------------------------------


class TestHooks:
    def test_add_hook_rejects_unknown_event(self) -> None:
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01)
        with pytest.raises(ValueError, match="Unknown hook event"):
            executor.add_hook("on_unknown_event", lambda **_: None)

    def test_add_hook_accepts_known_events(self) -> None:
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01)
        for event in (
            "on_task_complete",
            "on_task_failed",
            "on_workflow_complete",
            "on_workflow_failed",
        ):
            executor.add_hook(event, lambda **_: None)

    @pytest.mark.asyncio
    async def test_emit_invokes_sync_and_async_callbacks(self) -> None:
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        sync_calls: list[dict] = []
        async_calls: list[dict] = []

        def sync_cb(**kwargs: object) -> None:
            sync_calls.append(kwargs)

        async def async_cb(**kwargs: object) -> None:
            async_calls.append(kwargs)

        executor.add_hook("on_task_complete", sync_cb)
        executor.add_hook("on_task_complete", async_cb)

        await executor._emit("on_task_complete", subject="T1", status="completed")

        assert sync_calls == [{"subject": "T1", "status": "completed"}]
        assert async_calls == [{"subject": "T1", "status": "completed"}]

    @pytest.mark.asyncio
    async def test_emit_uses_inspect_iscoroutinefunction(self, monkeypatch) -> None:
        """Lock in the #256 migration: _emit must dispatch via inspect, not asyncio."""
        import inspect as _inspect

        from telemachy import executor as executor_mod

        calls: list[Callable[..., object]] = []
        real = _inspect.iscoroutinefunction

        def spy(cb: Callable[..., object]) -> bool:
            calls.append(cb)
            return real(cb)

        monkeypatch.setattr(executor_mod.inspect, "iscoroutinefunction", spy)

        sync_called = False
        async_called = False

        def sync_cb(**_: object) -> None:
            nonlocal sync_called
            sync_called = True

        async def async_cb(**_: object) -> None:
            nonlocal async_called
            async_called = True

        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01)
        executor.add_hook("on_task_complete", sync_cb)
        executor.add_hook("on_task_complete", async_cb)
        await executor._emit("on_task_complete", subject="T1", status="completed")

        assert sync_called and async_called
        assert sync_cb in calls and async_cb in calls

    @pytest.mark.asyncio
    async def test_monitor_completion_does_not_leak_emitted_subjects_across_calls(
        self,
    ) -> None:
        """Calling _monitor_completion twice on the same executor must re-emit
        callbacks for tasks with subjects seen in a prior call (#162)."""
        from telemachy.models import WorkflowState

        client = _make_mock_client()
        client.get_tasks = AsyncMock(return_value=[{"subject": "T1", "status": "completed"}])

        executor = WorkflowExecutor(client, poll_interval=0.01)
        calls: list[str] = []
        executor.add_hook("on_task_complete", lambda **kw: calls.append(kw["task"]["subject"]))

        spec = _make_spec()
        state = WorkflowState(
            workflow_id="wf-1",
            spec=spec,
            status="running",
            started_at="2026-06-03T00:00:00+00:00",
        )
        state.created_teams = {"team-a": "team-id-001"}

        await executor._monitor_completion(state)
        await executor._monitor_completion(state)

        # Each call must independently emit on_task_complete for T1.
        assert calls == ["T1", "T1"], (
            f"Expected two emissions across two monitor calls, got {calls!r} — "
            "state leaked between calls (#162 regression)"
        )

        # And the executor must not retain any emitted-event state on self.
        assert not hasattr(executor, "_emitted_task_events"), (
            "WorkflowExecutor must not carry per-monitor state on self (#162)"
        )


# ---------------------------------------------------------------------------
# Tests: timeout behaviour (#142)
# ---------------------------------------------------------------------------


class TestWorkflowTimeout:
    @pytest.mark.asyncio
    async def test_execute_raises_workflow_timeout_error_on_wait_for_timeout(self) -> None:
        client = _make_mock_client()
        spec = _make_spec()
        spec.timeout_seconds = 0.01  # immediate timeout

        executor = WorkflowExecutor(client, poll_interval=0.01)

        async def slow_run(_spec: object, _workflow_id: object = None) -> object:
            import asyncio as _a

            await _a.sleep(10)
            return None

        with (
            patch.object(executor, "_run", new=slow_run),
            pytest.raises(WorkflowTimeoutError, match="exceeded its execution timeout"),
        ):
            await executor.execute(spec)


# ---------------------------------------------------------------------------
# Tests: stop-event graceful cancellation (#143)
# ---------------------------------------------------------------------------


class TestStopEvent:
    @pytest.mark.asyncio
    async def test_stop_event_set_before_execute_short_circuits_monitor(self) -> None:
        import asyncio as _a

        client = _make_mock_client()
        spec = _make_spec(teardown="never")

        stop_event = _a.Event()
        stop_event.set()  # pre-set: monitor must observe it on first iteration

        executor = WorkflowExecutor(client, poll_interval=0.01, stop_event=stop_event)
        state = await executor.execute(spec)

        # Workflow finishes (not hangs) when stop event is set.
        assert state.completed_at is not None


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_rerun_reuses_existing_agent(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec()
        existing_key = make_key("test-wf", "worker")
        client = _make_mock_client()
        client.list_agents = AsyncMock(
            return_value=[{"id": "preexisting-agent-id", "name": existing_key}]
        )
        executor = WorkflowExecutor(client, poll_interval=0.01)
        state = await executor.execute(spec)
        client.create_agent.assert_not_called()
        assert state.created_agents["worker"] == "preexisting-agent-id"

    @pytest.mark.asyncio
    async def test_rerun_reuses_existing_team_and_task(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec()
        team_key = make_key("test-wf", "team-a")
        client = _make_mock_client()
        client.list_teams = AsyncMock(
            return_value=[{"id": "preexisting-team-id", "name": team_key}]
        )
        client.get_tasks = AsyncMock(
            return_value=[
                {"id": "preexisting-task-id", "subject": "Task 1", "status": "completed"},
            ]
        )
        executor = WorkflowExecutor(client, poll_interval=0.01)
        await executor.execute(spec)
        client.create_team.assert_not_called()
        client.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_bypasses_idempotency(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec()
        existing_key = make_key("test-wf", "worker")
        client = _make_mock_client()
        client.list_agents = AsyncMock(return_value=[{"id": "old-agent", "name": existing_key}])
        executor = WorkflowExecutor(client, poll_interval=0.01, force=True)
        state = await executor.execute(spec)
        client.create_agent.assert_called_once()
        assert state.created_agents["worker"] == "agent-id-001"

    @pytest.mark.asyncio
    async def test_partial_prior_run_completes_missing_resources(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec()
        client = _make_mock_client()
        client.list_agents = AsyncMock(
            return_value=[{"id": "reused-agent", "name": make_key("test-wf", "worker")}]
        )
        await WorkflowExecutor(client, poll_interval=0.01).execute(spec)
        client.create_agent.assert_not_called()
        client.create_team.assert_called_once()
        assert client.create_team.call_args.args[0] == make_key("test-wf", "team-a")

    @pytest.mark.asyncio
    async def test_reuse_tolerates_already_running_agent(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec()
        client = _make_mock_client()
        client.list_agents = AsyncMock(
            return_value=[{"id": "reused-agent", "name": make_key("test-wf", "worker")}]
        )
        # wake_agent raises a 409-shaped conflict on the reused agent
        client.wake_agent = AsyncMock(side_effect=AgamemnonError(409, "agent is already running"))
        # Must NOT raise; reuse continues.
        state = await WorkflowExecutor(client, poll_interval=0.01).execute(spec)
        assert state.status == "completed"
        assert state.created_agents["worker"] == "reused-agent"

    @pytest.mark.asyncio
    async def test_reuse_propagates_non_conflict_wake_error(self) -> None:
        from telemachy.idempotency import make_key

        spec = _make_spec(teardown="never")
        client = _make_mock_client()
        client.list_agents = AsyncMock(
            return_value=[{"id": "reused-agent", "name": make_key("test-wf", "worker")}]
        )
        client.wake_agent = AsyncMock(side_effect=AgamemnonError(500, "internal error"))
        state = await WorkflowExecutor(client, poll_interval=0.01).execute(spec)
        assert state.status == "failed"
        assert state.error is not None and "500" in state.error


# ---------------------------------------------------------------------------
# Tests: rate limiting under concurrent provisioning (#160)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_respects_rate_limit_under_gather() -> None:
    """20 agents under asyncio.gather + rate=20/s, burst=5 → elapsed in [0.6, 4.0]s.

    Math: each agent issues two throttled calls (`create_agent` + `wake_agent`),
    so 20 agents = 40 calls through `_request_with_retry`. At rate=20/burst=5
    the minimum is (40 - 5) / 20 = 1.75s on the rate-limited side. Upper bound
    widened to 4.0s to absorb CI variance and the single-vCPU edge case
    flagged in the prior review.
    """
    from telemachy.agamemnon_client import AgamemnonClient

    real_client = AgamemnonClient(
        url="https://test.local",
        require_tls=True,
        rate_limit_rps=20.0,
        rate_limit_burst=5,
    )
    real_client._client = MagicMock()
    real_client._client.request = AsyncMock(
        return_value=MagicMock(
            status_code=201, is_error=False, json=lambda: {"agent": {"id": "a"}}, text=""
        )
    )

    # Patch high-level methods to short-circuit team/task/monitor work
    real_client.get_tasks = AsyncMock(return_value=[{"subject": "T", "status": "completed"}])
    real_client.create_team = AsyncMock(return_value="team-1")
    real_client.create_task = AsyncMock(return_value="task-1")

    agents = [{"name": f"a{i}", "runtime": "local"} for i in range(20)]
    spec = _make_spec(
        agents=agents,
        tasks=[{"subject": "T", "description": "...", "assign_to": "a0"}],
        teardown="never",
    )
    executor = WorkflowExecutor(real_client, poll_interval=0.01)

    start = _time.monotonic()
    await executor.execute(spec)
    elapsed = _time.monotonic() - start
    assert 0.6 <= elapsed <= 4.0


# ---------------------------------------------------------------------------
# Tests: state persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    @pytest.mark.asyncio
    async def test_state_writer_called_at_each_transition(self) -> None:
        """state_writer fires for pending, running, and completed."""
        saved_statuses: list[str] = []
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01, state_writer=lambda s: saved_statuses.append(s.status))
        spec = _make_spec()
        await executor.execute(spec)
        assert saved_statuses[0] == "pending"
        assert "running" in saved_statuses
        assert saved_statuses[-1] == "completed"

    @pytest.mark.asyncio
    async def test_execute_accepts_workflow_id_override(self) -> None:
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01)
        spec = _make_spec()
        result = await executor.execute(spec, workflow_id="custom-42")
        assert result.workflow_id == "custom-42"

    @pytest.mark.asyncio
    async def test_stop_event_triggers_cancelled_status_and_persists(self) -> None:
        """stop_event → state.status='cancelled' AND disk reflects it."""
        import asyncio as _a

        saved_statuses: list[str] = []
        stop = _a.Event()
        stop.set()
        client = _make_mock_client()
        executor = WorkflowExecutor(
            client, poll_interval=0.01, stop_event=stop,
            state_writer=lambda s: saved_statuses.append(s.status),
        )
        spec = _make_spec(teardown="never")
        result = await executor.execute(spec)
        assert result.status == "cancelled"
        assert "cancelled" in saved_statuses

    @pytest.mark.asyncio
    async def test_state_writer_exception_does_not_crash_workflow(self) -> None:
        """If state_writer raises, the workflow continues."""
        def broken_writer(_s: object) -> None:
            raise OSError("disk full")

        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01, state_writer=broken_writer)
        spec = _make_spec()
        result = await executor.execute(spec)
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# Tests: audit trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_executor_emits_full_event_sequence(self, tmp_path: pytest.TempPathFactory) -> None:  # type: ignore
        import json

        from telemachy.audit import AuditSink

        log = tmp_path / "audit.jsonl"
        sink = AuditSink(path=log, host_id="test-host", hash_chain=True)
        client = _make_mock_client()
        executor = WorkflowExecutor(client, poll_interval=0.01, sink=sink)
        await executor.execute(_make_spec())
        sink.close()
        records = [json.loads(line) for line in log.read_text().splitlines()]
        events = [r["event_type"] for r in records]
        assert events[0] == "workflow.started"
        assert "agent.created" in events
        assert "team.created" in events
        assert "task.submitted" in events
        assert "task.completed" in events
        assert "workflow.completed" in events
        # Chain continuity end-to-end
        for i in range(1, len(records)):
            assert records[i]["prev_hash"] == records[i - 1]["hash"]
        # Actor present on every record
        for r in records:
            assert r["actor"]["host_id"] == "test-host"
