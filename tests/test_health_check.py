"""Tests for Agamemnon health-check + event-bus connectivity (issues #161, #3).

`client.ping()` health-probing is unchanged. Mid-workflow connectivity loss is
now detected by the NATS event monitor (`monitor.connected`) rather than an HTTP
heartbeat poll (#3); a lost event bus raises NatsUnavailableError, sets
state.connectivity_failed, and — critically (#161) — still triggers teardown
under an on_completion policy so agents/teams do not leak.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from telemachy.agamemnon_client import AgamemnonClient
from telemachy.executor import WorkflowExecutor
from telemachy.models import WorkflowSpec
from tests.conftest import _create_mock_nats_monitor


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


def _disconnected_monitor() -> MagicMock:
    """A NATS monitor mock that is connected at enter but reports a mid-workflow
    disconnect: tasks never reach a terminal status and `connected` is False, so
    `_wait_for_all_terminal` raises NatsUnavailableError."""
    monitor = _create_mock_nats_monitor()
    monitor.connected = False
    # Tasks never become terminal, so the wait loop must rely on the connectivity
    # check (not a terminal event) to break out.
    monitor.latest_status = MagicMock(return_value="in_progress")

    import asyncio

    def _unset_event(_subject: str) -> asyncio.Event:
        return asyncio.Event()  # never set

    monitor.terminal_event = MagicMock(side_effect=_unset_event)
    return monitor


# === ping() tests ===


class TestPing:
    @pytest.mark.asyncio
    async def test_ping_returns_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock(spec=AgamemnonClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_response)

        real_client = AgamemnonClient(url="http://localhost:8080")
        real_client._client = client._http

        result = await real_client.ping(timeout=5.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock(spec=AgamemnonClient)
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        real_client = AgamemnonClient(url="http://localhost:8080")
        real_client._client = client._http

        result = await real_client.ping(timeout=5.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_connect_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock(spec=AgamemnonClient)
        client._http = AsyncMock()
        client._http.request = AsyncMock(side_effect=httpx.ConnectError("connect failed"))

        real_client = AgamemnonClient(url="http://localhost:8080")
        real_client._client = client._http

        result = await real_client.ping(timeout=5.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock(spec=AgamemnonClient)
        mock_response = MagicMock()
        mock_response.status_code = 503
        client._http = AsyncMock()
        client._http.request = AsyncMock(return_value=mock_response)

        real_client = AgamemnonClient(url="http://localhost:8080")
        real_client._client = client._http

        result = await real_client.ping(timeout=5.0)
        assert result is False


# === event-bus connectivity loss (NATS) ===


class TestMonitorConnectivity:
    @pytest.mark.asyncio
    async def test_mid_workflow_disconnect_fails_workflow(self) -> None:
        """A NATS disconnect mid-monitoring fails the workflow and flags
        state.connectivity_failed (the event-driven successor to #161's
        HTTP-heartbeat connectivity detection)."""
        client = _make_mock_client()
        spec = _make_spec()
        monitor = _disconnected_monitor()

        with patch("telemachy.executor.NatsMonitor", return_value=monitor):
            executor = WorkflowExecutor(client, poll_interval=0.01)
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.connectivity_failed is True
        assert state.error is not None and "NATS connection lost" in state.error

    @pytest.mark.asyncio
    async def test_nats_unavailable_at_connect_fails_workflow(self) -> None:
        """If NATS cannot be reached at all, the workflow fails fast."""
        from telemachy.nats_monitor import NatsUnavailableError

        client = _make_mock_client()
        spec = _make_spec()
        monitor = _create_mock_nats_monitor()
        monitor.__aenter__.side_effect = NatsUnavailableError("NATS unreachable")

        with patch("telemachy.executor.NatsMonitor", return_value=monitor):
            executor = WorkflowExecutor(client, poll_interval=0.01)
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.connectivity_failed is True
        assert "NATS" in (state.error or "")


# === teardown policy regression tests (#161) ===


class TestTeardownPolicy:
    @pytest.mark.asyncio
    async def test_connectivity_error_triggers_teardown_under_on_failure(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(teardown="on_failure")
        monitor = _disconnected_monitor()

        with patch("telemachy.executor.NatsMonitor", return_value=monitor):
            executor = WorkflowExecutor(client, poll_interval=0.01)
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.connectivity_failed is True
        client.delete_agent.assert_called()
        client.delete_team.assert_called()

    @pytest.mark.asyncio
    async def test_connectivity_error_triggers_teardown_under_on_completion(self) -> None:
        """Critical resource-leak regression test for issue #161.

        With teardown: on_completion (the default in workflows/example.yaml),
        a connectivity-induced failure must still trigger teardown.
        Without this, agents and teams leak.
        """
        client = _make_mock_client()
        spec = _make_spec(teardown="on_completion")
        monitor = _disconnected_monitor()

        with patch("telemachy.executor.NatsMonitor", return_value=monitor):
            executor = WorkflowExecutor(client, poll_interval=0.01)
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.connectivity_failed is True
        # The critical fix: connectivity failure triggers teardown under on_completion.
        client.delete_agent.assert_called()
        client.delete_team.assert_called()

    @pytest.mark.asyncio
    async def test_connectivity_error_skips_teardown_under_never(self) -> None:
        client = _make_mock_client()
        spec = _make_spec(teardown="never")
        monitor = _disconnected_monitor()

        with patch("telemachy.executor.NatsMonitor", return_value=monitor):
            executor = WorkflowExecutor(client, poll_interval=0.01)
            state = await executor.execute(spec)

        assert state.status == "failed"
        assert state.connectivity_failed is True
        client.delete_agent.assert_not_called()
        client.delete_team.assert_not_called()
