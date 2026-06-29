"""Tests for Agamemnon health-check functionality (issue #161)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from telemachy.agamemnon_client import AgamemnonClient
from telemachy.executor import WorkflowExecutor
from telemachy.models import WorkflowSpec


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
    client.ping = AsyncMock(return_value=True)
    client.create_team = AsyncMock(return_value="team-id-001")
    client.create_task = AsyncMock(return_value="task-id-001")
    client.update_task = AsyncMock()
    client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "completed"}])
    client.delete_team = AsyncMock()
    return client


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


# === heartbeat threshold tests ===


class TestHeartbeatThreshold:
    @pytest.mark.asyncio
    async def test_single_ping_failure_does_not_trip_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        client.ping = AsyncMock(side_effect=[False, True, True, True])

        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        # Monitor should complete normally; single ping failure should not trip threshold
        state = await executor.execute(spec)
        assert state.status == "completed"
        assert state.connectivity_failed is False

    @pytest.mark.asyncio
    async def test_two_consecutive_ping_failures_trip_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        # Two consecutive failures should trip threshold
        client.ping = AsyncMock(side_effect=[False, False])
        # Never complete tasks so we stay in monitoring
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The exception is caught and the workflow fails
        assert state.status == "failed"
        assert state.connectivity_failed is True


# === end-to-end integration test ===


class TestMonitorConnectivity:
    @pytest.mark.asyncio
    async def test_monitor_raises_connectivity_error_after_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        # Permanently failing ping
        client.ping = AsyncMock(return_value=False)
        # Never complete tasks
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The WorkflowConnectivityError is caught and the workflow fails
        assert state.status == "failed"
        assert state.connectivity_failed is True
        assert "consecutive health checks" in state.error


# === heartbeat lifecycle tests ===


class TestHeartbeatLifecycle:
    @pytest.mark.asyncio
    async def test_heartbeat_cancelled_on_normal_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)

        client = _make_mock_client()
        client.ping = AsyncMock(return_value=True)
        # Complete immediately
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "completed"}])

        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        assert state.status == "completed"
        assert state.connectivity_failed is False

    @pytest.mark.asyncio
    async def test_heartbeat_returns_cleanly_on_connectivity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        # Two consecutive failures trip the threshold
        client.ping = AsyncMock(side_effect=[False, False])
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec()
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The heartbeat returns cleanly after tripping the threshold,
        # and the error is caught in the main executor
        assert state.status == "failed"
        assert state.connectivity_failed is True


# === teardown policy regression tests ===


class TestTeardownPolicy:
    @pytest.mark.asyncio
    async def test_connectivity_error_triggers_teardown_under_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        client.ping = AsyncMock(side_effect=[False, False])
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec(teardown="on_failure")
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The exception becomes "failed" status, which matches the on_failure policy
        assert state.status == "failed"
        assert state.connectivity_failed is True
        # Verify teardown WAS called
        client.delete_agent.assert_called()
        client.delete_team.assert_called()

    @pytest.mark.asyncio
    async def test_connectivity_error_triggers_teardown_under_on_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Critical resource-leak regression test for issue #161.

        With teardown: on_completion (the default in workflows/example.yaml),
        a connectivity-induced failure must still trigger teardown.
        Without this, agents and teams leak.
        """
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        client.ping = AsyncMock(side_effect=[False, False])
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec(teardown="on_completion")
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The critical fix: connectivity failure should trigger teardown under on_completion
        assert state.status == "failed"
        assert state.connectivity_failed is True
        # Verify teardown WAS called (the critical fix for the resource leak)
        client.delete_agent.assert_called()
        client.delete_team.assert_called()

    @pytest.mark.asyncio
    async def test_connectivity_error_skips_teardown_under_never(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_interval_seconds", 0.01)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_failure_threshold", 2)
        monkeypatch.setattr("telemachy.executor.settings.healthcheck_timeout_seconds", 0.01)

        client = _make_mock_client()
        client.ping = AsyncMock(side_effect=[False, False])
        client.get_tasks = AsyncMock(return_value=[{"subject": "Task 1", "status": "running"}])

        spec = _make_spec(teardown="never")
        executor = WorkflowExecutor(client, poll_interval=0.01)

        state = await executor.execute(spec)
        # The workflow fails due to connectivity, but teardown is never called
        assert state.status == "failed"
        assert state.connectivity_failed is True
        # Verify teardown was NOT called
        client.delete_agent.assert_not_called()
        client.delete_team.assert_not_called()
