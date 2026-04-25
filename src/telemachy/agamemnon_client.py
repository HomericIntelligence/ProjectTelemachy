"""Async HTTP client wrapping the ProjectAgamemnon REST API."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from telemachy.models import AgentSpec, TaskSpec


class AgamemnonError(Exception):
    """Raised when the ProjectAgamemnon API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Agamemnon API error {status_code}: {message}")


def _require(data: dict[str, Any], *keys: str, context: str = "") -> Any:
    """Safely traverse nested dict keys, raising AgamemnonError on missing keys."""
    val: Any = data
    for k in keys:
        if not isinstance(val, dict) or k not in val:
            ctx = f" in {context}" if context else ""
            raise AgamemnonError(
                0,
                f"Unexpected API response shape{ctx}: missing key {k!r}. Got: {val!r}",
            )
        val = val[k]
    return val


class AgamemnonClient:
    """Async client for ProjectAgamemnon REST API endpoints used by Telemachy."""

    def __init__(self, url: str, api_key: str = "") -> None:
        self._base_url = url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._headers = headers
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AgamemnonClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("AgamemnonClient must be used as an async context manager")
        return self._client

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise AgamemnonError(response.status_code, detail)

    async def _request_with_retry(
        self, method: str, url: str, *, max_attempts: int = 3, **kwargs: Any
    ) -> httpx.Response:
        """Issue an HTTP request, retrying on server errors and transient failures."""
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                resp = await self._http.request(method, url, **kwargs)
                if resp.status_code < 500:
                    return resp
                last_exc = AgamemnonError(resp.status_code, f"Server error {resp.status_code}")
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(2**attempt)
        raise AgamemnonError(0, f"Request failed after {max_attempts} attempts: {last_exc}")

    # === Agent endpoints ===

    async def create_agent(self, spec: AgentSpec) -> str:
        """Create a local or docker agent. Returns the Agamemnon agent id."""
        if spec.runtime == "docker":
            return await self._create_docker_agent(spec)
        return await self._create_local_agent(spec)

    async def _create_local_agent(self, spec: AgentSpec) -> str:
        payload: dict[str, object] = {
            "name": spec.name,
            "label": spec.name,
            "program": spec.program,
            "workingDirectory": spec.working_dir,
            "taskDescription": f"Telemachy-managed agent: {spec.name}",
        }
        if spec.model:
            payload["programArgs"] = f"--model {spec.model}"

        response = await self._request_with_retry("POST", "/v1/agents", json=payload)
        self._raise_for_status(response)
        return str(_require(response.json(), "agent", "id", context="create_agent"))

    async def _create_docker_agent(self, spec: AgentSpec) -> str:
        payload: dict[str, object] = {
            "name": spec.name,
            "hostId": "hermes",
            "image": spec.docker_image,
            "cpus": spec.cpus,
            "memory": spec.memory,
            "workingDirectory": spec.working_dir,
        }

        response = await self._request_with_retry("POST", "/v1/agents/docker", json=payload)
        self._raise_for_status(response)
        return str(_require(response.json(), "agent", "id", context="create_docker_agent"))

    async def wake_agent(self, agent_id: str) -> None:
        """Start a stopped agent."""
        response = await self._request_with_retry("POST", f"/v1/agents/{agent_id}/start")
        self._raise_for_status(response)

    async def hibernate_agent(self, agent_id: str) -> None:
        """Stop a running agent."""
        response = await self._request_with_retry("POST", f"/v1/agents/{agent_id}/stop")
        self._raise_for_status(response)

    async def delete_agent(self, agent_id: str) -> None:
        """Permanently delete an agent."""
        response = await self._request_with_retry("DELETE", f"/v1/agents/{agent_id}")
        self._raise_for_status(response)

    async def list_agents(self) -> list[dict[str, object]]:
        """List all agents."""
        response = await self._request_with_retry("GET", "/v1/agents")
        self._raise_for_status(response)
        return response.json().get("agents", [])  # type: ignore[return-value]

    # === Team endpoints ===

    async def create_team(self, name: str, agent_ids: list[str]) -> str:
        """Create a team, then set members. Returns the Agamemnon team id."""
        response = await self._request_with_retry("POST", "/v1/teams", json={"name": name})
        self._raise_for_status(response)
        team_id = str(_require(response.json(), "team", "id", context="create_team"))
        if agent_ids:
            r2 = await self._request_with_retry(
                "PUT", f"/v1/teams/{team_id}", json={"agentIds": agent_ids}
            )
            self._raise_for_status(r2)
        return team_id

    async def delete_team(self, team_id: str) -> None:
        """Delete a team."""
        response = await self._request_with_retry("DELETE", f"/v1/teams/{team_id}")
        self._raise_for_status(response)

    # === Task endpoints ===

    async def create_task(
        self, team_id: str, spec: TaskSpec, blocked_by_ids: list[str] | None = None
    ) -> str:
        """Create a task within a team. Returns the Agamemnon task id."""
        payload: dict[str, object] = {
            "subject": spec.subject,
            "description": spec.description,
        }
        if spec.assign_to:
            payload["assigneeAgentId"] = spec.assign_to
        if blocked_by_ids:
            payload["blockedBy"] = blocked_by_ids

        response = await self._request_with_retry(
            "POST", f"/v1/teams/{team_id}/tasks", json=payload
        )
        self._raise_for_status(response)
        return str(_require(response.json(), "task", "id", context="create_task"))

    async def update_task(
        self,
        team_id: str,
        task_id: str,
        status: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> dict[str, object]:
        """Update a task's status or assignment."""
        payload: dict[str, object] = {}
        if status is not None:
            payload["status"] = status
        if assignee_agent_id is not None:
            payload["assigneeAgentId"] = assignee_agent_id

        response = await self._request_with_retry(
            "PUT", f"/v1/teams/{team_id}/tasks/{task_id}", json=payload
        )
        self._raise_for_status(response)
        return response.json()  # type: ignore[return-value]

    async def get_tasks(self, team_id: str) -> list[dict[str, object]]:
        """List all tasks for a team."""
        response = await self._request_with_retry("GET", f"/v1/teams/{team_id}/tasks")
        self._raise_for_status(response)
        return _require(response.json(), "tasks", context="get_tasks")  # type: ignore[return-value]
