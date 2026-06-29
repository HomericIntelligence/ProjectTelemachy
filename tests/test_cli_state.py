"""Tests for the CLI status, list, and cancel commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from telemachy.cli import app
from telemachy.config import Settings
from telemachy.models import WorkflowSpec, WorkflowState

runner = CliRunner()


def _make_state(
    workflow_id: str = "test-id",
    name: str = "test-workflow",
    status: str = "completed",
) -> WorkflowState:
    """Create a minimal WorkflowState for testing."""
    spec = WorkflowSpec(
        metadata={"name": name},
        agents=[],
        teams=[],
    )
    return WorkflowState(
        workflow_id=workflow_id,
        spec=spec,
        status=status,
        started_at="2026-06-03T10:00:00+00:00",
    )


class TestStatusCommand:
    def test_status_missing_workflow_exits_1(self, tmp_path: Path, monkeypatch) -> None:
        """status command exits 1 when workflow not found."""
        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["status", "nonexistent-id"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_status_shows_state(self, tmp_path: Path, monkeypatch) -> None:
        """status command shows persisted workflow state."""
        from telemachy.state_store import FileStateStore

        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        store = FileStateStore(tmp_path)

        state = _make_state(workflow_id="test-id", name="my-workflow", status="running")
        store.save(state)

        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["status", "test-id"])

        assert result.exit_code == 0
        assert "test-id" in result.output
        assert "my-workflow" in result.output
        assert "running" in result.output


class TestListCommand:
    def test_list_empty(self, tmp_path: Path, monkeypatch) -> None:
        """list command shows 'No workflows recorded' when state dir is empty."""
        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "no workflows recorded" in result.output.lower()

    def test_list_shows_all(self, tmp_path: Path, monkeypatch) -> None:
        """list command shows all workflows in state dir."""
        from telemachy.state_store import FileStateStore

        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        store = FileStateStore(tmp_path)

        state1 = _make_state(workflow_id="wf-1", name="workflow-one", status="completed")
        state2 = _make_state(workflow_id="wf-2", name="workflow-two", status="failed")
        store.save(state1)
        store.save(state2)

        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "wf-1" in result.output
        assert "wf-2" in result.output
        assert "workflow-one" in result.output
        assert "workflow-two" in result.output


class TestCancelCommand:
    def test_cancel_running_writes_sentinel(self, tmp_path: Path, monkeypatch) -> None:
        """cancel command writes sentinel for running workflow."""
        from telemachy.state_store import FileStateStore

        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        store = FileStateStore(tmp_path)

        state = _make_state(workflow_id="wf-running", status="running")
        store.save(state)

        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["cancel", "wf-running"])

        assert result.exit_code == 0
        assert "cancellation requested" in result.output.lower()
        # Verify sentinel was written
        assert store.is_cancel_requested("wf-running")

    def test_cancel_completed_reports_noop(self, tmp_path: Path, monkeypatch) -> None:
        """cancel command reports no-op for already completed workflow."""
        from telemachy.state_store import FileStateStore

        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        store = FileStateStore(tmp_path)

        state = _make_state(workflow_id="wf-done", status="completed")
        store.save(state)

        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["cancel", "wf-done"])

        assert result.exit_code == 0
        assert "already completed" in result.output.lower()
        # No sentinel should be written
        assert not store.is_cancel_requested("wf-done")

    def test_cancel_missing_exits_1(self, tmp_path: Path, monkeypatch) -> None:
        """cancel command exits 1 when workflow not found."""
        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["cancel", "nonexistent-id"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_cancel_corrupt_state_exits_1(self, tmp_path: Path, monkeypatch) -> None:
        """cancel command exits 1 when state file is corrupt."""
        from telemachy.state_store import FileStateStore

        monkeypatch.setenv("TELEMACHY_STATE_DIR", str(tmp_path))
        mock_settings = Settings(_env_file=None)
        store = FileStateStore(tmp_path)

        # Write a corrupt state file
        corrupt_path = store._state_path("corrupt-id")
        corrupt_path.write_text("{")

        with patch("telemachy.cli.settings", mock_settings):
            result = runner.invoke(app, ["cancel", "corrupt-id"])

        assert result.exit_code == 1
        assert "corrupt" in result.output.lower()
