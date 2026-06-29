"""File-backed persistence for WorkflowState and cancellation signals."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from telemachy.models import WorkflowState

logger = logging.getLogger(__name__)

_VALID_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class WorkflowNotFoundError(LookupError):
    """Raised when a workflow_id has no persisted state file."""


class CorruptStateError(RuntimeError):
    """Raised when a state file exists but cannot be parsed (corruption or schema drift)."""


def _validate_id(workflow_id: str) -> None:
    if not workflow_id or len(workflow_id) > 64:
        raise ValueError(f"invalid workflow_id: {workflow_id!r}")
    if "\x00" in workflow_id:
        raise ValueError("workflow_id contains null byte")
    if not all(c in _VALID_ID_CHARS for c in workflow_id.lower()):
        raise ValueError(f"workflow_id contains illegal characters: {workflow_id!r}")


class FileStateStore:
    def __init__(self, state_dir: Path) -> None:
        self._dir = state_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._dir, 0o700)
        except OSError as exc:
            logger.debug("could not chmod %s to 0700: %s", self._dir, exc)

    def _state_path(self, workflow_id: str) -> Path:
        _validate_id(workflow_id)
        return self._dir / f"{workflow_id}.json"

    def _cancel_path(self, workflow_id: str) -> Path:
        _validate_id(workflow_id)
        return self._dir / f"{workflow_id}.cancel"

    def save(self, state: WorkflowState) -> None:
        target = self._state_path(state.workflow_id)
        data = state.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{state.workflow_id}.", suffix=".tmp", dir=self._dir
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, target)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def load(self, workflow_id: str) -> WorkflowState:
        path = self._state_path(workflow_id)
        if not path.exists():
            raise WorkflowNotFoundError(workflow_id)
        try:
            return WorkflowState.model_validate_json(path.read_text())
        except ValidationError as exc:
            raise CorruptStateError(
                f"state file {path} is corrupt or from an incompatible schema: {exc}"
            ) from exc

    def list(self) -> list[WorkflowState]:
        out: list[WorkflowState] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                out.append(WorkflowState.model_validate_json(p.read_text()))
            except (ValidationError, OSError) as exc:
                logger.warning("skipping unreadable state file %s: %s", p, exc)
        return out

    def request_cancel(self, workflow_id: str) -> WorkflowState:
        """Write the cancel sentinel iff workflow is non-terminal. Returns loaded state."""
        state = self.load(workflow_id)  # raises WorkflowNotFoundError if missing
        if state.status in {"completed", "failed", "cancelled"}:
            return state
        sentinel = self._cancel_path(workflow_id)
        sentinel.touch(mode=0o600)
        return state

    def is_cancel_requested(self, workflow_id: str) -> bool:
        try:
            return self._cancel_path(workflow_id).exists()
        except ValueError:
            return False

    def clear_cancel(self, workflow_id: str) -> None:
        with contextlib.suppress(ValueError):
            self._cancel_path(workflow_id).unlink(missing_ok=True)
