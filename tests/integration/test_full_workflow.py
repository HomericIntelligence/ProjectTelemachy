"""Integration tests: full workflow lifecycle vs. mock Agamemnon HTTP server."""

from __future__ import annotations

import json

import pytest

from telemachy.executor import WorkflowExecutor
from tests.integration.conftest import make_spec, payload_contains

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_full_lifecycle_provisions_then_tears_down(mock_agamemnon) -> None:
    state, router, client = mock_agamemnon
    state.task_status_script["do-it"] = ["completed"]

    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(make_spec())

    assert result.status == "completed"
    assert result.created_agents == {"worker": "agent-0001"}
    assert result.created_teams == {"t1": "team-0002"}

    # Schema-shape assertion on the exact agent-creation payload.
    create_call = router["create_agent"].calls.last
    payload = json.loads(create_call.request.read())
    assert payload_contains(
        payload,
        {
            "name": "worker",
            "label": "worker",
            "program": "claude-code",
            "workingDirectory": "/tmp",
            "taskDescription": "Telemachy-managed agent: worker",
        },
    )
    # Task-creation payload uses RESOLVED agent id, not the name.
    task_payload = json.loads(router["create_task"].calls.last.request.read())
    assert payload_contains(
        task_payload,
        {"subject": "do-it", "description": "x", "assigneeAgentId": "agent-0001"},
    )
    # Teardown ran: DELETE /v1/teams/{id} and DELETE /v1/agents/{id} both fired.
    assert router["delete_team"].called
    assert router["delete_agent"].called
    assert state.agents == {}
    assert state.teams == {}


async def test_blocked_by_waits_for_predecessor(mock_agamemnon) -> None:
    state, router, client = mock_agamemnon
    state.task_status_script["A"] = ["pending", "completed", "completed"]
    state.task_status_script["B"] = ["completed"]
    spec = make_spec(
        teams=[
            {
                "name": "t1",
                "agents": ["worker"],
                "tasks": [
                    {"subject": "A", "description": "first", "assign_to": "worker"},
                    {
                        "subject": "B",
                        "description": "second",
                        "assign_to": "worker",
                        "blocked_by": ["A"],
                    },
                ],
            }
        ]
    )
    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(spec)

    assert result.status == "completed"
    # B must have been submitted AFTER A.
    create_task_payloads = [json.loads(c.request.read()) for c in router["create_task"].calls]
    subjects_in_order = [p["subject"] for p in create_task_payloads]
    assert subjects_in_order == ["A", "B"]


async def test_docker_agent_routes_to_docker_endpoint(mock_agamemnon) -> None:
    state, router, client = mock_agamemnon
    spec = make_spec(agents=[{"name": "worker", "runtime": "docker", "docker_image": "img:1"}])
    state.task_status_script["do-it"] = ["completed"]
    executor = WorkflowExecutor(client, poll_interval=0.01)
    await executor.execute(spec)

    assert router["create_docker_agent"].called
    assert not router["create_agent"].called
    payload = json.loads(router["create_docker_agent"].calls.last.request.read())
    assert payload_contains(
        payload,
        {"name": "worker", "image": "img:1", "cpus": 2, "memory": "4g"},
    )


async def test_update_task_drives_put_route(mock_agamemnon) -> None:
    """AgamemnonClient.update_task exercises PUT /v1/teams/{id}/tasks/{id}."""
    state, router, client = mock_agamemnon
    state.tasks["team-1"] = [{"id": "task-1", "subject": "do-it", "status": "pending"}]

    result = await client.update_task("team-1", "task-1", status="completed")

    assert router["update_task"].called
    assert result["task"]["status"] == "completed"
    assert state.tasks["team-1"][0]["status"] == "completed"


async def test_yaml_to_execution_roundtrip(mock_agamemnon) -> None:
    """YAML string → WorkflowSpec → executor → mock Agamemnon → completed."""
    import yaml

    state, _, client = mock_agamemnon
    yaml_text = (
        "apiVersion: telemachy/v1\n"
        "metadata: {name: smoke, description: y}\n"
        "agents:\n"
        "  - {name: w, runtime: local}\n"
        "teams:\n"
        "  - name: t\n"
        "    agents: [w]\n"
        "    tasks:\n"
        "      - {subject: s, description: d, assign_to: w}\n"
        "teardown: on_completion\n"
    )
    from telemachy.models import WorkflowSpec

    spec = WorkflowSpec.model_validate(yaml.safe_load(yaml_text))
    state.task_status_script["s"] = ["completed"]
    executor = WorkflowExecutor(client, poll_interval=0.01)
    result = await executor.execute(spec)
    assert result.status == "completed"
