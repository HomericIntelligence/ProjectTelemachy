"""Register a workflow as a GitHub epic with child issues (Odysseus ADR-013 §6).

Telemachy owns work *description*: this module turns a validated
:class:`~telemachy.models.WorkflowSpec` into one GitHub child issue per task
plus an epic issue whose body is the parseable task list

.. code-block:: markdown

    - [ ] #123 (depends on: #456)
    - [ ] #124

then publishes ``hi.pipeline.epic.{epic_key}.registered`` so Agamemnon picks
the epic up for HMAS decomposition. GitHub access goes through the ``gh``
CLI (already the ecosystem convention); NATS publish uses the same deferred
nats-py import pattern as :mod:`telemachy.nats_monitor`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from telemachy.models import TaskSpec, WorkflowSpec

logger = logging.getLogger(__name__)

EPIC_LABEL = "agamemnon-epic"
CHILD_LABEL = "state:needs-plan"
EPIC_SUBJECT = "hi.pipeline.epic.{epic_key}.registered"
TASK_MARKER = "<!-- telemachy:task {workflow}/{subject} -->"

_TOKEN_RE = re.compile(r"[^a-z0-9-]+")
_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")


def slugify(value: str) -> str:
    """Slugify *value* into a single NATS subject token (ADR-005 rules)."""
    return _TOKEN_RE.sub("-", value.lower()).strip("-")


def epic_key(repo: str, issue_number: int) -> str:
    """Build the ADR-013 §6 epic key ``{repo_slug}-{issue_number}``."""
    return f"{slugify(repo)}-{issue_number}"


def envelope(**fields: Any) -> dict[str, Any]:
    """Build an ADR-013 §3 ``hi/v1`` payload envelope merged with *fields*."""
    return {
        "schema": "hi/v1",
        "ts": datetime.now(UTC).isoformat(),
        "msg_id": str(uuid.uuid4()),
        **fields,
    }


def ordered_tasks(spec: WorkflowSpec) -> list[TaskSpec]:
    """Return all tasks across teams in dependency order (deps first).

    ``WorkflowSpec`` validation already rejects cycles and unknown
    references, so Kahn's algorithm here always drains completely.
    """
    tasks = [task for team in spec.teams for task in team.tasks]
    by_subject = {task.subject: task for task in tasks}
    remaining = dict(by_subject)
    ordered: list[TaskSpec] = []
    while remaining:
        ready = [
            subject
            for subject, task in remaining.items()
            if all(dep not in remaining for dep in task.blocked_by)
        ]
        for subject in ready:
            ordered.append(remaining.pop(subject))
    return ordered


def _run_gh(args: list[str]) -> str:
    """Run one ``gh`` command and return stdout."""
    result = subprocess.run(  # noqa: S603  # nosec B603 — fixed gh binary, list argv
        ["gh", *args], capture_output=True, text=True, check=True, timeout=60
    )
    return result.stdout


def _parse_issue_number(output: str) -> int:
    """Extract the issue number from ``gh issue create`` output (the URL)."""
    match = _ISSUE_URL_RE.search(output)
    if match is None:
        raise RuntimeError(f"could not parse issue number from gh output: {output!r}")
    return int(match.group(1))


def _child_body(spec: WorkflowSpec, task: TaskSpec, dep_numbers: list[int]) -> str:
    """Render one child issue body (marker + description + dependency lines)."""
    marker = TASK_MARKER.format(workflow=spec.name, subject=task.subject)
    lines = [marker, "", task.description.strip(), ""]
    lines.append(
        f"_Registered from Telemachy workflow `{spec.name}`; assign_to `{task.assign_to}`._"
    )
    for number in dep_numbers:
        lines.append(f"Depends on #{number}")
    return "\n".join(lines)


def _epic_body(spec: WorkflowSpec, children: dict[str, int], tasks: list[TaskSpec]) -> str:
    """Render the epic body with the ADR-013 §6 parseable task list."""
    lines = [spec.description.strip() or spec.name, "", "## Tasks", ""]
    for task in tasks:
        line = f"- [ ] #{children[task.subject]}"
        deps = [children[dep] for dep in task.blocked_by]
        if deps:
            line += " (depends on: " + ", ".join(f"#{n}" for n in deps) + ")"
        lines.append(line)
    lines += ["", f"_Registered by Telemachy from workflow `{spec.name}`._"]
    return "\n".join(lines)


async def _publish(subject: str, payload: dict[str, Any], nats_url: str) -> None:
    """Publish *payload* on *subject* (token auth per Odysseus ADR-009)."""
    import nats as _nats

    kwargs: dict[str, Any] = {}
    token = os.environ.get("NATS_CLIENT_TOKEN")
    if token:
        kwargs["token"] = token
    nc = await _nats.connect(nats_url, allow_reconnect=False, connect_timeout=3, **kwargs)
    try:
        await nc.publish(subject, json.dumps(payload).encode())
        await nc.flush()
    finally:
        await nc.close()


def _default_publish(subject: str, payload: dict[str, Any], nats_url: str) -> None:
    """Synchronous wrapper for the async NATS publish."""
    asyncio.run(_publish(subject, payload, nats_url))


def register_epic(
    spec: WorkflowSpec,
    *,
    repo: str | None = None,
    nats_url: str = "nats://localhost:4222",
    dry_run: bool = False,
    gh: Callable[[list[str]], str] = _run_gh,
    publish: Callable[[str, dict[str, Any], str], None] = _default_publish,
) -> dict[str, Any]:
    """Create the epic + child issues for *spec* and publish the trigger.

    Returns the JSON-serialisable result contract:
    ``{"epic": N, "key": ..., "children": {subject: N, ...}, "subject": ...}``.

    Args:
        spec: Validated workflow to describe.
        repo: Target ``OWNER/NAME``; defaults to the current directory's repo.
        nats_url: NATS server for the registration trigger.
        dry_run: Plan only — no issues created, nothing published.
        gh: ``gh`` CLI runner (injectable for tests).
        publish: NATS publisher (injectable for tests).

    """
    if repo is None:
        repo = json.loads(gh(["repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]
    repo_args = ["--repo", repo]
    tasks = ordered_tasks(spec)

    if dry_run:
        return {
            "epic": None,
            "key": None,
            "repo": repo,
            "children": {task.subject: None for task in tasks},
            "dry_run": True,
        }

    # Labels are idempotent to create; a failure (e.g. exists with another
    # color) must not block registration.
    for label, color, description in (
        (CHILD_LABEL, "bfd4f2", "Awaiting a plan from the planning stage"),
        (EPIC_LABEL, "5319e7", "Epic tracked by Agamemnon HMAS orchestration"),
    ):
        try:
            gh(
                [
                    "label",
                    "create",
                    label,
                    *repo_args,
                    "--color",
                    color,
                    "--description",
                    description,
                    "--force",
                ]
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("label create %s failed (continuing): %s", label, exc)

    children: dict[str, int] = {}
    for task in tasks:
        dep_numbers = [children[dep] for dep in task.blocked_by]
        output = gh(
            [
                "issue",
                "create",
                *repo_args,
                "--title",
                task.subject,
                "--body",
                _child_body(spec, task, dep_numbers),
                "--label",
                CHILD_LABEL,
            ]
        )
        children[task.subject] = _parse_issue_number(output)

    epic_output = gh(
        [
            "issue",
            "create",
            *repo_args,
            "--title",
            f"[epic] {spec.name}",
            "--body",
            _epic_body(spec, children, tasks),
            "--label",
            EPIC_LABEL,
        ]
    )
    epic_number = _parse_issue_number(epic_output)
    key = epic_key(repo, epic_number)
    subject = EPIC_SUBJECT.format(epic_key=key)

    payload = envelope(
        epic={"repo": repo, "issue": epic_number, "key": key},
        children=sorted(children.values()),
        workflow=spec.name,
    )
    publish(subject, payload, nats_url)
    logger.info("registered epic #%s on %s (key %s)", epic_number, repo, key)

    return {
        "epic": epic_number,
        "key": key,
        "repo": repo,
        "children": children,
        "subject": subject,
    }
