"""Tests for Pydantic workflow models."""

from __future__ import annotations

import pytest
import yaml

from telemachy.models import AgentSpec, TaskSpec, TeamSpec, WorkflowSpec


MINIMAL_WORKFLOW_YAML = """
apiVersion: telemachy/v1
metadata:
  name: test-workflow
  description: A minimal test workflow
agents:
  - name: worker
    program: claude-code
    runtime: local
teams:
  - name: team-a
    agents:
      - worker
    tasks:
      - subject: "Do the thing"
        description: "Do something useful"
        assign_to: worker
teardown: on_completion
"""

TWO_TASK_DEP_YAML = """
apiVersion: telemachy/v1
metadata:
  name: dep-workflow
  description: Workflow with task dependency
agents:
  - name: agent-a
    runtime: local
  - name: agent-b
    runtime: local
teams:
  - name: dep-team
    agents:
      - agent-a
      - agent-b
    tasks:
      - subject: "Step 1"
        description: "First step"
        assign_to: agent-a
      - subject: "Step 2"
        description: "Second step, depends on Step 1"
        assign_to: agent-b
        blocked_by:
          - "Step 1"
teardown: on_completion
"""


class TestWorkflowSpecParsing:
    def test_minimal_workflow_parses(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        spec = WorkflowSpec.model_validate(raw)
        assert spec.name == "test-workflow"
        assert len(spec.agents) == 1
        assert spec.agents[0].name == "worker"
        assert len(spec.teams) == 1
        assert len(spec.teams[0].tasks) == 1
        assert spec.teardown == "on_completion"

    def test_dependency_workflow_parses(self) -> None:
        raw = yaml.safe_load(TWO_TASK_DEP_YAML)
        spec = WorkflowSpec.model_validate(raw)
        team = spec.teams[0]
        step2 = next(t for t in team.tasks if t.subject == "Step 2")
        assert step2.blocked_by == ["Step 1"]

    def test_agent_defaults(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        spec = WorkflowSpec.model_validate(raw)
        agent = spec.agents[0]
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

    def test_unknown_agent_in_team_raises(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        raw["teams"][0]["agents"].append("nonexistent-agent")
        with pytest.raises(Exception, match="unknown agent"):
            WorkflowSpec.model_validate(raw)

    def test_unknown_assign_to_raises(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        raw["teams"][0]["tasks"][0]["assign_to"] = "ghost"
        with pytest.raises(Exception, match="not in team"):
            WorkflowSpec.model_validate(raw)

    def test_teardown_default_is_on_completion(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        del raw["teardown"]
        spec = WorkflowSpec.model_validate(raw)
        assert spec.teardown == "on_completion"

    def test_invalid_teardown_raises(self) -> None:
        raw = yaml.safe_load(MINIMAL_WORKFLOW_YAML)
        raw["teardown"] = "immediately"
        with pytest.raises(Exception):
            WorkflowSpec.model_validate(raw)


class TestDependencyCycleDetection:
    def test_cycle_raises(self) -> None:
        raw = {
            "apiVersion": "telemachy/v1",
            "metadata": {"name": "cycle-test"},
            "agents": [{"name": "a"}],
            "teams": [
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
            "teardown": "never",
        }
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
        with pytest.raises(Exception, match="itself"):
            TaskSpec(
                subject="Task X",
                description="...",
                assign_to="a",
                blocked_by=["Task X"],
            )
            # The validator runs at model level; construct TeamSpec to trigger it
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
        raw = yaml.safe_load(TWO_TASK_DEP_YAML)
        # Should not raise
        spec = WorkflowSpec.model_validate(raw)
        assert spec is not None
