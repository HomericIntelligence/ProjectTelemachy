"""Async HTTP client wrapping the ai-maestro REST API."""

from __future__ import annotations

import httpx

from telemachy.models import AgentSpec, TaskSpec


class MaestroError(Exception):
    """Raised when the ai-maestro API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"ai-maestro API error {status_code}: {message}")


class MaestroClient:
    """Async client for all ai-maestro REST API endpoints used by Telemachy."""

    def __init__(self, url: str, api_key: str = "") -> None:
        self._base_url = url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._headers = headers
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MaestroClient":
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
            raise RuntimeError("MaestroClient must be used as an async context manager")
        return self._client

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise MaestroError(response.status_code, detail)

    # === Agent endpoints ===

    async def create_agent(self, spec: AgentSpec) -> str:
        """Create a local or docker agent. Returns the maestro agent id."""
        if spec.runtime == "docker":
            return await self._create_docker_agent(spec)
        return await self._create_local_agent(spec)

    async def _create_local_agent(self, spec: AgentSpec) -> str:
        payload: dict[str, object] = {
            "name": spec.name,
            "program": spec.program,
            "working_dir": spec.working_dir,
        }
        if spec.model:
            payload["model"] = spec.model

        response = await self._http.post("/api/agents", json=payload)
        self._raise_for_status(response)
        data = response.json()
        return str(data["id"])

    async def _create_docker_agent(self, spec: AgentSpec) -> str:
        payload: dict[str, object] = {
            "name": spec.name,
            "program": spec.program,
            "working_dir": spec.working_dir,
            "image": spec.docker_image,
            "cpus": spec.cpus,
            "memory": spec.memory,
        }
        if spec.model:
            payload["model"] = spec.model

        response = await self._http.post("/api/agents/docker/create", json=payload)
        self._raise_for_status(response)
        data = response.json()
        return str(data["id"])

    async def wake_agent(self, agent_id: str) -> None:
        """Wake a hibernated agent."""
        response = await self._http.post(f"/api/agents/{agent_id}/wake")
        self._raise_for_status(response)

    async def hibernate_agent(self, agent_id: str) -> None:
        """Hibernate a running agent."""
        response = await self._http.post(f"/api/agents/{agent_id}/hibernate")
        self._raise_for_status(response)

    async def delete_agent(self, agent_id: str) -> None:
        """Permanently delete an agent."""
        response = await self._http.delete(f"/api/agents/{agent_id}")
        self._raise_for_status(response)

    async def list_agents(self) -> list[dict[str, object]]:
        """List all agents across all hosts (unified view)."""
        response = await self._http.get("/api/agents/unified")
        self._raise_for_status(response)
        return response.json()  # type: ignore[return-value]

    # === Team endpoints ===

    async def create_team(self, name: str, agent_ids: list[str]) -> str:
        """Create a team with the given agents. Returns the maestro team id."""
        payload: dict[str, object] = {
            "name": name,
            "agent_ids": agent_ids,
        }
        response = await self._http.post("/api/teams", json=payload)
        self._raise_for_status(response)
        data = response.json()
        return str(data["id"])

    # === Task endpoints ===

    async def create_task(self, team_id: str, spec: TaskSpec) -> str:
        """Create a task within a team. Returns the maestro task id."""
        payload: dict[str, object] = {
            "title": spec.title,
            "description": spec.description,
            "assigned_to": spec.assign_to,
        }
        response = await self._http.post(f"/api/teams/{team_id}/tasks", json=payload)
        self._raise_for_status(response)
        data = response.json()
        return str(data["id"])

    async def update_task(
        self,
        team_id: str,
        task_id: str,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> None:
        """Update a task's status or assignment."""
        payload: dict[str, object] = {}
        if status is not None:
            payload["status"] = status
        if assigned_to is not None:
            payload["assigned_to"] = assigned_to

        response = await self._http.put(
            f"/api/teams/{team_id}/tasks/{task_id}", json=payload
        )
        self._raise_for_status(response)

    async def get_tasks(self, team_id: str) -> list[dict[str, object]]:
        """List all tasks for a team."""
        response = await self._http.get(f"/api/teams/{team_id}/tasks")
        self._raise_for_status(response)
        return response.json()  # type: ignore[return-value]
