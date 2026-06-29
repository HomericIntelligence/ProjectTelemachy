"""In-process ASGI stub of the ProjectAgamemnon REST API used by Telemachy.

Implements every endpoint AgamemnonClient calls. Unknown paths return HTTP 501
with a 'stub_unimplemented' marker (and are recorded in self.unhandled) so a
new Agamemnon endpoint surfaces as a loud, named test failure.

Per-task status sequences are fixed ONLY at construction time. There is no
setter — calling code that needs scripted transitions must pass them to
StubAgamemnon(task_statuses=...).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _StubTask:
    id: str
    subject: str
    description: str
    blocked_by: list[str] = field(default_factory=list)
    assignee_agent_id: str | None = None
    status_sequence: list[str] = field(default_factory=lambda: ["pending", "completed"])
    _poll_count: int = 0

    def next_status(self) -> str:
        idx = min(self._poll_count, len(self.status_sequence) - 1)
        self._poll_count += 1
        return self.status_sequence[idx]


class StubAgamemnonError(AssertionError):
    """Raised when the stub is asked to do something outside its known surface."""


class StubAgamemnon:
    """Minimal in-memory stand-in for the ProjectAgamemnon REST API."""

    def __init__(self, task_statuses: dict[str, list[str]] | None = None) -> None:
        self._task_statuses: dict[str, list[str]] = dict(task_statuses or {})
        self.agents: dict[str, dict[str, Any]] = {}
        self.teams: dict[str, dict[str, Any]] = {}
        self.team_members: dict[str, list[str]] = {}
        self.tasks: dict[str, dict[str, _StubTask]] = {}
        self.calls: list[tuple[str, str]] = []
        self.unhandled: list[tuple[str, str]] = []
        self._agent_ids = (f"agent-{i}" for i in itertools.count(1))
        self._team_ids = (f"team-{i}" for i in itertools.count(1))
        self._task_ids = (f"task-{i}" for i in itertools.count(1))

    async def asgi(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "http"
        method = scope["method"]
        path = scope["path"]
        self.calls.append((method, path))
        body_chunks: list[bytes] = []
        more = True
        while more:
            msg = await receive()
            body_chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        payload = json.loads(b"".join(body_chunks)) if any(body_chunks) else {}
        status, resp = self._dispatch(method, path, payload)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(resp).encode()})

    @staticmethod
    def _segment(path: str, idx: int) -> str:
        parts = path.split("/")
        if len(parts) <= idx:
            raise StubAgamemnonError(f"stub: cannot read segment {idx} from path {path!r}")
        return parts[idx]

    def _dispatch(
        self, method: str, path: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        # ---- Agents ----
        if method == "POST" and path == "/v1/agents":
            agent_id = next(self._agent_ids)
            self.agents[agent_id] = {
                "id": agent_id,
                "name": body.get("name", ""),
                "status": "stopped",
            }
            return 201, {"agent": {"id": agent_id}}
        if method == "POST" and path == "/v1/agents/docker":
            agent_id = next(self._agent_ids)
            self.agents[agent_id] = {
                "id": agent_id,
                "name": body.get("name", ""),
                "status": "stopped",
                "image": body.get("image"),
            }
            return 201, {"agent": {"id": agent_id}}
        if method == "POST" and path.startswith("/v1/agents/") and path.endswith("/start"):
            agent_id = self._segment(path, 3)
            if agent_id not in self.agents:
                return 404, {"detail": f"agent {agent_id} not found"}
            self.agents[agent_id]["status"] = "running"
            return 200, {}
        if method == "POST" and path.startswith("/v1/agents/") and path.endswith("/stop"):
            agent_id = self._segment(path, 3)
            if agent_id in self.agents:
                self.agents[agent_id]["status"] = "stopped"
            return 200, {}
        if method == "DELETE" and path.startswith("/v1/agents/"):
            # /v1/agents/{id} only — no sub-resource matches this clause
            tail = path[len("/v1/agents/") :]
            if "/" in tail:
                self.unhandled.append((method, path))
                return 501, {
                    "detail": "stub_unimplemented",
                    "method": method,
                    "path": path,
                    "hint": "Add this endpoint to tests/stub_agamemnon.py._dispatch",
                }
            self.agents.pop(tail, None)
            return 204, {}
        if method == "GET" and path == "/v1/agents":
            return 200, {"agents": list(self.agents.values())}

        # ---- Teams ----
        if method == "POST" and path == "/v1/teams":
            team_id = next(self._team_ids)
            self.teams[team_id] = {"id": team_id, "name": body.get("name", "")}
            self.tasks[team_id] = {}
            return 201, {"team": {"id": team_id}}
        if method == "PUT" and path.startswith("/v1/teams/") and "/tasks" not in path:
            team_id = self._segment(path, 3)
            self.team_members[team_id] = list(body.get("agentIds", []))
            return 200, {}
        if method == "DELETE" and path.startswith("/v1/teams/") and "/tasks" not in path:
            team_id = self._segment(path, 3)
            self.teams.pop(team_id, None)
            self.tasks.pop(team_id, None)
            return 204, {}
        if method == "GET" and path == "/v1/teams":
            # Used by WorkflowExecutor's idempotency snapshot (list_teams).
            return 200, {"teams": list(self.teams.values())}

        # ---- Tasks ----
        if method == "POST" and path.startswith("/v1/teams/") and path.endswith("/tasks"):
            team_id = self._segment(path, 3)
            task_id = next(self._task_ids)
            subject = body["subject"]
            self.tasks[team_id][task_id] = _StubTask(
                id=task_id,
                subject=subject,
                description=body.get("description", ""),
                blocked_by=list(body.get("blockedBy", []) or []),
                assignee_agent_id=body.get("assigneeAgentId"),
                status_sequence=self._task_statuses.get(subject, ["pending", "completed"]),
            )
            return 201, {"task": {"id": task_id}}
        if method == "GET" and path.startswith("/v1/teams/") and path.endswith("/tasks"):
            team_id = self._segment(path, 3)
            tasks_payload = [
                {
                    "id": t.id,
                    "subject": t.subject,
                    "status": t.next_status(),
                    "blockedBy": t.blocked_by,
                }
                for t in self.tasks.get(team_id, {}).values()
            ]
            return 200, {"tasks": tasks_payload}
        if method == "PUT" and "/tasks/" in path:
            return 200, {}

        # ---- Unknown ----
        self.unhandled.append((method, path))
        return 501, {
            "detail": "stub_unimplemented",
            "method": method,
            "path": path,
            "hint": "Add this endpoint to tests/stub_agamemnon.py._dispatch",
        }
