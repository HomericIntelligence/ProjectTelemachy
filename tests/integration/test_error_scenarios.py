"""Integration tests: error scenarios vs. the mock Agamemnon HTTP server."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

import telemachy.agamemnon_client as ac_mod
from telemachy.executor import WorkflowExecutor
from tests.integration.conftest import make_spec

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# Defined BEFORE every test that uses it — addresses C1 (NameError at parse).
async def _no_sleep(_seconds: float) -> None:
    return None


@pytest_asyncio.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Patch out retry back-off sleeps so retry-heavy tests run instantly."""
    monkeypatch.setattr(ac_mod.asyncio, "sleep", _no_sleep)


async def test_500_during_create_agent_marks_workflow_failed(mock_agamemnon) -> None:
    """Every create_agent attempt 500s; retry budget exhausts; workflow fails."""
    state, _router, client = mock_agamemnon
    state.permanent_create_agent_status = 500

    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(make_spec(teardown="on_failure"))

    assert result.status == "failed"
    assert result.error is not None
    # No agents were ever recorded, so teardown of agents is a no-op,
    # but the policy IS on_failure → executor reached _teardown without exception.
    assert state.agents == {}


async def test_404_on_get_tasks_marks_workflow_failed(mock_agamemnon) -> None:
    """A 404 from GET /v1/teams/{id}/tasks during monitoring surfaces as failure."""
    state, _router, client = mock_agamemnon
    # A single 404 fails immediately (4xx is not retried); extra entries are unused.
    state.get_tasks_status_queue = [404, 404, 404]
    state.task_status_script["do-it"] = ["completed"]

    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(make_spec(teardown="on_failure"))

    assert result.status == "failed"
    assert result.error is not None


async def test_429_then_success_is_retried_transparently(mock_agamemnon) -> None:
    """429 then 201 — retry succeeds, workflow completes with the 2nd attempt's agent id."""
    state, _router, client = mock_agamemnon
    state.create_agent_status_queue = [429]  # next call returns 429, then queue empty → 201
    state.task_status_script["do-it"] = ["completed"]

    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(make_spec())

    assert result.status == "completed"
    # Two POST /v1/agents calls fired; created_agents maps to the successful one.
    assert len(result.created_agents) == 1


async def test_connect_error_during_provision_marks_failed(mock_agamemnon) -> None:
    """httpx.ConnectError from POST /v1/agents exhausts retries → workflow fails."""
    state, _router, client = mock_agamemnon
    state.create_agent_raise = httpx.ConnectError

    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(make_spec(teardown="on_failure"))

    assert result.status == "failed"
    assert result.error is not None


async def test_teardown_on_failure_actually_runs_after_provisioning_partial_success(
    mock_agamemnon,
) -> None:
    """Two agents requested; second fails after retry budget; first agent must be deleted by teardown."""
    state, router, client = mock_agamemnon
    # Agent 1 succeeds (201). Agent 2's three attempts all 500 → AgamemnonError.
    # Permanent override applies to ALL calls, so use the queue instead: first call ok (no queue entry),
    # then enqueue 500/500/500 for the second agent's retries.
    state.create_agent_status_queue = [201, 500, 500, 500]

    spec = make_spec(
        agents=[
            {"name": "a", "runtime": "local"},
            {"name": "b", "runtime": "local"},
        ],
        teams=[
            {
                "name": "t1",
                "agents": ["a", "b"],
                "tasks": [
                    {"subject": "ta", "description": "x", "assign_to": "a"},
                    {"subject": "tb", "description": "y", "assign_to": "b"},
                ],
            }
        ],
        teardown="on_failure",
    )
    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(spec)

    assert result.status == "failed"
    # The successfully-created agent must have been deleted by teardown.
    assert router["delete_agent"].called
    assert state.agents == {}
