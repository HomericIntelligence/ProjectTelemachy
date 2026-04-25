"""ProjectTelemachy — declarative workflow engine for ProjectAgamemnon."""

from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.config import Settings
from telemachy.executor import WorkflowExecutor
from telemachy.models import AgentSpec, TaskSpec, TeamSpec, WorkflowSpec, WorkflowState

version = "0.1.0"

__all__ = [
    "WorkflowExecutor",
    "AgamemnonClient",
    "AgamemnonError",
    "WorkflowSpec",
    "AgentSpec",
    "TeamSpec",
    "TaskSpec",
    "WorkflowState",
    "Settings",
]
