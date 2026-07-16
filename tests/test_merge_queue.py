"""Regression tests for GitHub merge-queue readiness."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_WORKFLOW = WORKFLOWS_DIR / "release.yml"
MERGE_QUEUE_RUNBOOK = REPO_ROOT / "docs" / "ci" / "merge-queue.md"

REQUIRED_CONTEXTS = {
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


def _targets_main_changes(on_block: dict[str, Any]) -> bool:
    for event in ("pull_request", "push"):
        config = on_block.get(event)
        if not isinstance(config, dict):
            continue
        branches = config.get("branches")
        if branches is not None and "main" in branches:
            return True
        if branches is None and event == "pull_request":
            return True
        if branches is None and event == "push" and "tags" not in config:
            return True
    return False


def test_required_context_workflows_support_merge_group_checks_requested() -> None:
    suppliers: dict[str, set[str]] = {}

    for path in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        workflow = _load_workflow(path)
        jobs = workflow.get("jobs", {})
        job_names = {
            job.get("name", job_id) for job_id, job in jobs.items() if isinstance(job, dict)
        }
        supplied_contexts = REQUIRED_CONTEXTS & job_names
        on_block = _on_block(workflow)
        if not supplied_contexts or not _targets_main_changes(on_block):
            continue

        suppliers[path.name] = supplied_contexts
        assert on_block.get("merge_group") == {"types": ["checks_requested"]}, (
            f"{path} supplies required contexts but does not handle merge_group/checks_requested"
        )

    emitted = set().union(*suppliers.values()) if suppliers else set()
    assert emitted == REQUIRED_CONTEXTS


def test_release_publisher_remains_tag_only() -> None:
    on_block = _on_block(_load_workflow(RELEASE_WORKFLOW))

    assert on_block["push"] == {"tags": ["v*.*.*"]}
    assert "pull_request" not in on_block
    assert "merge_group" not in on_block


def test_merge_queue_runbook_pins_approved_activation_policy() -> None:
    assert MERGE_QUEUE_RUNBOOK.is_file(), "merge-queue activation runbook is missing"
    text = MERGE_QUEUE_RUNBOOK.read_text()
    match = re.search(
        r"<!-- merge-queue-rule -->\s*```json\n(?P<policy>.*?)\n```",
        text,
        re.DOTALL,
    )
    assert match is not None, "runbook is missing its machine-readable merge-queue rule"

    assert json.loads(match.group("policy")) == {
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
    for context in REQUIRED_CONTEXTS:
        assert f"`{context}`" in text
