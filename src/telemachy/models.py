"""Pydantic models for the Telemachy workflow schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class AgentSpec(BaseModel):
    """Specification for a single ai-maestro agent to provision."""

    name: str
    program: str = "claude-code"
    model: str | None = None
    working_dir: str = "/tmp"
    runtime: Literal["local", "docker"] = "local"
    docker_image: str | None = None
    cpus: int = 2
    memory: str = "4g"

    @model_validator(mode="after")
    def docker_requires_image(self) -> "AgentSpec":
        if self.runtime == "docker" and not self.docker_image:
            raise ValueError(
                f"Agent '{self.name}': docker_image is required when runtime is 'docker'"
            )
        return self


class TaskSpec(BaseModel):
    """Specification for a single task within a team."""

    subject: str
    description: str
    assign_to: str  # agent name
    blocked_by: list[str] = []


class TeamSpec(BaseModel):
    """Specification for a team of agents and their tasks."""

    name: str
    agents: list[str]  # agent names — must match names in WorkflowSpec.agents
    tasks: list[TaskSpec]

    @field_validator("tasks")
    @classmethod
    def no_self_dependency(cls, tasks: list[TaskSpec]) -> list[TaskSpec]:
        for task in tasks:
            if task.subject in task.blocked_by:
                raise ValueError(
                    f"Task '{task.subject}' cannot depend on itself"
                )
        return tasks

    def detect_dependency_cycles(self) -> None:
        """Raise ValueError if task dependencies contain a cycle."""
        task_subjects = {t.subject for t in self.tasks}
        deps: dict[str, list[str]] = {t.subject: t.blocked_by for t in self.tasks}

        # Validate all blocked_by references exist
        for task in self.tasks:
            for dep in task.blocked_by:
                if dep not in task_subjects:
                    raise ValueError(
                        f"Task '{task.subject}' depends on unknown task '{dep}'"
                    )

        # Topological sort (Kahn's algorithm) to detect cycles
        in_degree: dict[str, int] = {t: 0 for t in task_subjects}
        for subject, task_deps in deps.items():
            for dep in task_deps:
                in_degree[subject] += 1

        queue = [t for t, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for subject, task_deps in deps.items():
                if node in task_deps:
                    in_degree[subject] -= 1
                    if in_degree[subject] == 0:
                        queue.append(subject)

        if visited != len(task_subjects):
            raise ValueError(
                f"Team '{self.name}' has a dependency cycle in its tasks"
            )


class WorkflowSpec(BaseModel):
    """Top-level workflow specification parsed from a workflow YAML file."""

    apiVersion: str = "telemachy/v1"
    metadata: dict[str, str]
    agents: list[AgentSpec]
    teams: list[TeamSpec]
    teardown: Literal["on_completion", "on_failure", "never"] = "on_completion"

    @model_validator(mode="after")
    def validate_references(self) -> "WorkflowSpec":
        agent_names = {a.name for a in self.agents}

        for team in self.teams:
            # Validate agent references in team
            for agent_name in team.agents:
                if agent_name not in agent_names:
                    raise ValueError(
                        f"Team '{team.name}' references unknown agent '{agent_name}'"
                    )
            # Validate task assign_to references
            for task in team.tasks:
                if task.assign_to not in agent_names:
                    raise ValueError(
                        f"Task '{task.subject}' assigns to unknown agent '{task.assign_to}'"
                    )
            # Check for dependency cycles
            team.detect_dependency_cycles()

        return self

    @property
    def name(self) -> str:
        return self.metadata.get("name", "unnamed")

    @property
    def description(self) -> str:
        return self.metadata.get("description", "")


class WorkflowState(BaseModel):
    """Runtime state for a workflow execution."""

    workflow_id: str
    spec: WorkflowSpec
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    created_agents: dict[str, str] = {}  # agent name → maestro agent id
    created_teams: dict[str, str] = {}   # team name → maestro team id
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
