"""Regression tests for GitHub merge-queue readiness."""

import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
REQUIRED_WORKFLOW = WORKFLOWS_DIR / "_required.yml"
RELEASE_WORKFLOW = WORKFLOWS_DIR / "release.yml"
MERGE_QUEUE_POLICY = REPO_ROOT / "configs" / "github" / "merge-queue-policy.json"

EXPECTED_REQUIRED_CONTEXTS = [
    "build",
    "deps/version-sync",
    "install",
    "integration-tests",
    "lint",
    "package",
    "release",
    "schema-validation",
    "security/dependency-scan",
    "security/secrets-scan",
    "test",
    "unit-tests",
]

EXPECTED_MERGE_QUEUE_RULE = {
    "type": "merge_queue",
    "parameters": {
        "check_response_timeout_minutes": 60,
        "grouping_strategy": "ALLGREEN",
        "max_entries_to_build": 10,
        "max_entries_to_merge": 5,
        "merge_method": "SQUASH",
        "min_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 5,
    },
}


def _load_workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path} must contain a workflow mapping"
    return data


def _on_block(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the Actions trigger block despite PyYAML's YAML 1.1 `on` coercion."""
    on_block = workflow.get(True, workflow.get("on"))
    assert isinstance(on_block, dict), "workflow `on` block must be a mapping"
    return on_block


def _load_policy() -> dict[str, Any]:
    policy = json.loads(MERGE_QUEUE_POLICY.read_text())
    assert isinstance(policy, dict), "merge-queue policy must be a JSON object"
    return policy


def test_policy_artifact_pins_exact_required_contexts() -> None:
    assert _load_policy()["required_contexts"] == EXPECTED_REQUIRED_CONTEXTS


def test_policy_artifact_pins_exact_approved_queue_rule() -> None:
    assert _load_policy()["merge_queue_rule"] == EXPECTED_MERGE_QUEUE_RULE


def test_required_workflow_push_main_block_is_exact() -> None:
    on_block = _on_block(_load_workflow(REQUIRED_WORKFLOW))
    assert on_block["push"] == {"branches": ["main"]}


def test_required_workflow_pull_request_main_block_is_exact() -> None:
    on_block = _on_block(_load_workflow(REQUIRED_WORKFLOW))
    assert on_block["pull_request"] == {"branches": ["main"]}


def test_required_workflow_merge_group_block_is_exact() -> None:
    on_block = _on_block(_load_workflow(REQUIRED_WORKFLOW))
    assert on_block["merge_group"] == {"types": ["checks_requested"]}


def test_required_workflow_emits_every_policy_context_exactly_once() -> None:
    jobs = _load_workflow(REQUIRED_WORKFLOW)["jobs"]
    emitted_names = [
        job.get("name", job_id) for job_id, job in jobs.items() if isinstance(job, dict)
    ]
    policy_contexts = _load_policy()["required_contexts"]

    emitted_policy_contexts = [name for name in emitted_names if name in policy_contexts]

    assert sorted(emitted_policy_contexts) == policy_contexts
    assert len(emitted_policy_contexts) == len(set(emitted_policy_contexts))


def test_release_publisher_remains_tag_only() -> None:
    on_block = _on_block(_load_workflow(RELEASE_WORKFLOW))

    assert on_block["push"] == {"tags": ["v*.*.*"]}
    assert "pull_request" not in on_block
    assert "merge_group" not in on_block
