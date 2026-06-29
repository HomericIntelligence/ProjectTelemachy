"""Tests for file-backed state persistence."""

import os

import pytest

from telemachy.models import WorkflowSpec, WorkflowState
from telemachy.state_store import (
    CorruptStateError,
    FileStateStore,
    WorkflowNotFoundError,
)


def _make_state(workflow_id: str = "test-id") -> WorkflowState:
    """Create a minimal WorkflowState for testing."""
    spec = WorkflowSpec(
        metadata={"name": "test"},
        agents=[],
        teams=[],
    )
    return WorkflowState(
        workflow_id=workflow_id,
        spec=spec,
        status="pending",
    )


def test_save_load_round_trip(tmp_path):
    store = FileStateStore(tmp_path)
    original = _make_state()
    store.save(original)
    loaded = store.load(original.workflow_id)
    assert loaded.workflow_id == original.workflow_id
    assert loaded.status == original.status


def test_save_is_atomic_on_replace_failure(tmp_path, monkeypatch):
    """If os.replace fails, the target must not exist and tmp must be cleaned."""
    store = FileStateStore(tmp_path)
    state = _make_state()

    def failing_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated disk full"):
        store.save(state)

    target = store._state_path(state.workflow_id)
    assert not target.exists()
    # Verify no stray .tmp files left behind
    tmp_files = list(tmp_path.glob(".*.tmp"))
    assert len(tmp_files) == 0


def test_save_sets_0600_file_permissions(tmp_path):
    store = FileStateStore(tmp_path)
    state = _make_state()
    store.save(state)
    path = store._state_path(state.workflow_id)
    assert path.stat().st_mode & 0o777 == 0o600


def test_state_dir_is_0700(tmp_path):
    store = FileStateStore(tmp_path)
    assert store._dir.stat().st_mode & 0o777 == 0o700


def test_load_missing_raises_not_found(tmp_path):
    store = FileStateStore(tmp_path)
    with pytest.raises(WorkflowNotFoundError):
        store.load("nonexistent")


def test_load_corrupt_raises_corrupt_state(tmp_path):
    store = FileStateStore(tmp_path)
    path = store._state_path("test-id")
    path.write_text("{")
    with pytest.raises(CorruptStateError):
        store.load("test-id")


def test_list_skips_corrupt_files(tmp_path):
    store = FileStateStore(tmp_path)
    # Write a valid state
    state = _make_state("valid-1")
    store.save(state)
    # Write a corrupt file
    corrupt_path = tmp_path / "corrupt-id.json"
    corrupt_path.write_text("{")
    # list() should return only the valid state, warning about corrupt
    states = store.list()
    assert len(states) == 1
    assert states[0].workflow_id == "valid-1"


def test_list_returns_empty_for_empty_dir(tmp_path):
    store = FileStateStore(tmp_path)
    states = store.list()
    assert states == []


def test_request_cancel_writes_sentinel_on_running(tmp_path):
    store = FileStateStore(tmp_path)
    state = _make_state()
    store.save(state)
    result = store.request_cancel("test-id")
    assert result.status == "pending"
    sentinel = store._cancel_path("test-id")
    assert sentinel.exists()


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
def test_request_cancel_noop_on_each_terminal_state(tmp_path, terminal_status):
    store = FileStateStore(tmp_path)
    state = _make_state()
    state.status = terminal_status
    store.save(state)
    result = store.request_cancel("test-id")
    assert result.status == terminal_status
    sentinel = store._cancel_path("test-id")
    assert not sentinel.exists()


def test_request_cancel_missing_raises(tmp_path):
    store = FileStateStore(tmp_path)
    with pytest.raises(WorkflowNotFoundError):
        store.request_cancel("nonexistent")


def test_is_cancel_requested_false_when_no_sentinel(tmp_path):
    store = FileStateStore(tmp_path)
    assert not store.is_cancel_requested("test-id")


def test_is_cancel_requested_true_after_request(tmp_path):
    store = FileStateStore(tmp_path)
    state = _make_state()
    store.save(state)
    store.request_cancel("test-id")
    assert store.is_cancel_requested("test-id")


def test_clear_cancel_removes_sentinel(tmp_path):
    store = FileStateStore(tmp_path)
    state = _make_state()
    store.save(state)
    store.request_cancel("test-id")
    assert store.is_cancel_requested("test-id")
    store.clear_cancel("test-id")
    assert not store.is_cancel_requested("test-id")


def test_validate_id_rejects_path_traversal(tmp_path):
    store = FileStateStore(tmp_path)
    with pytest.raises(ValueError, match="illegal characters"):
        store.load("../etc/passwd")


def test_validate_id_rejects_null_byte(tmp_path):
    store = FileStateStore(tmp_path)
    with pytest.raises(ValueError, match="null byte"):
        store.load("id\x00")


def test_validate_id_rejects_empty_and_overlong(tmp_path):
    store = FileStateStore(tmp_path)
    with pytest.raises(ValueError, match="invalid workflow_id"):
        store.load("")
    with pytest.raises(ValueError, match="invalid workflow_id"):
        store.load("x" * 65)
