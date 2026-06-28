"""Tests for Pydantic workflow models."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from telemachy.models import AgentSpec, TaskSpec, TeamSpec, WorkflowSpec
from tests.conftest import make_agent_dict, make_two_task_dep_dict


class TestWorkflowSpecParsing:
    def test_minimal_workflow_parses(
        self, workflow_spec_factory: Callable[..., WorkflowSpec]
    ) -> None:
        spec = workflow_spec_factory()
        assert spec.name == "test-workflow"
        assert len(spec.agents) == 1
        assert spec.agents[0].name == "worker"
        assert len(spec.teams) == 1
        assert len(spec.teams[0].tasks) == 1
        assert spec.teardown == "on_completion"

    def test_dependency_workflow_parses(self) -> None:
        spec = WorkflowSpec.model_validate(make_two_task_dep_dict())
        team = spec.teams[0]
        step2 = next(t for t in team.tasks if t.subject == "Step 2")
        assert step2.blocked_by == ["Step 1"]

    def test_agent_defaults(self, workflow_spec_factory: Callable[..., WorkflowSpec]) -> None:
        agent = workflow_spec_factory().agents[0]
        assert agent.program == "claude-code"
        assert agent.runtime == "local"
        assert agent.working_dir == "/tmp"
        assert agent.model is None

    def test_docker_agent_requires_image(self) -> None:
        with pytest.raises(Exception, match="docker_image"):
            AgentSpec(name="bad-docker", runtime="docker")

    def test_docker_agent_with_image_valid(self) -> None:
        agent = AgentSpec(
            name="docker-agent",
            runtime="docker",
            docker_image="ghcr.io/example/image:latest",
        )
        assert agent.docker_image == "ghcr.io/example/image:latest"

    def test_unknown_agent_in_team_raises(
        self, workflow_dict_factory: Callable[..., dict[str, Any]]
    ) -> None:
        raw = workflow_dict_factory()
        raw["teams"][0]["agents"].append("nonexistent-agent")
        with pytest.raises(Exception, match="unknown agent"):
            WorkflowSpec.model_validate(raw)

    def test_unknown_assign_to_raises(
        self, workflow_dict_factory: Callable[..., dict[str, Any]]
    ) -> None:
        raw = workflow_dict_factory()
        raw["teams"][0]["tasks"][0]["assign_to"] = "ghost"
        with pytest.raises(Exception, match="not in team"):
            WorkflowSpec.model_validate(raw)

    def test_teardown_default_is_on_completion(
        self, workflow_dict_factory: Callable[..., dict[str, Any]]
    ) -> None:
        raw = workflow_dict_factory()
        del raw["teardown"]
        spec = WorkflowSpec.model_validate(raw)
        assert spec.teardown == "on_completion"

    def test_invalid_teardown_raises(
        self, workflow_dict_factory: Callable[..., dict[str, Any]]
    ) -> None:
        raw = workflow_dict_factory()
        raw["teardown"] = "immediately"
        with pytest.raises(ValueError):
            WorkflowSpec.model_validate(raw)


class TestDependencyCycleDetection:
    def test_cycle_raises(self, workflow_dict_factory: Callable[..., dict[str, Any]]) -> None:
        raw = workflow_dict_factory(
            name="cycle-test",
            agents=[make_agent_dict("a")],
            teams=[
                {
                    "name": "cycle-team",
                    "agents": ["a"],
                    "tasks": [
                        {
                            "subject": "Task A",
                            "description": "...",
                            "assign_to": "a",
                            "blocked_by": ["Task B"],
                        },
                        {
                            "subject": "Task B",
                            "description": "...",
                            "assign_to": "a",
                            "blocked_by": ["Task A"],
                        },
                    ],
                }
            ],
            teardown="never",
        )
        with pytest.raises(Exception, match="cycle"):
            WorkflowSpec.model_validate(raw)

    def test_unknown_depends_on_raises(self) -> None:
        team = TeamSpec(
            name="t",
            agents=["a"],
            tasks=[
                TaskSpec(
                    subject="Task 1",
                    description="desc",
                    assign_to="a",
                    blocked_by=["Nonexistent Task"],
                )
            ],
        )
        with pytest.raises(ValueError, match="unknown task"):
            team.detect_dependency_cycles()

    def test_self_dependency_raises(self) -> None:
        # The self-dependency validator lives on TeamSpec.no_self_dependency;
        # construct a TeamSpec containing the offending TaskSpec so the
        # validator actually runs (the prior version of this test had an
        # unreachable second TeamSpec(...) after the first raised — see #147).
        with pytest.raises(Exception, match="itself"):
            TeamSpec(
                name="t",
                agents=["a"],
                tasks=[
                    TaskSpec(
                        subject="Task X",
                        description="...",
                        assign_to="a",
                        blocked_by=["Task X"],
                    )
                ],
            )

    def test_linear_dependency_chain_ok(self) -> None:
        # Should not raise
        spec = WorkflowSpec.model_validate(make_two_task_dep_dict())
        assert spec is not None
