"""WorkflowExecutor: orchestrates the full workflow lifecycle via ai-maestro."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from telemachy.config import settings
from telemachy.maestro_client import MaestroClient, MaestroError
from telemachy.models import AgentSpec, TaskSpec, TeamSpec, WorkflowSpec, WorkflowState

logger = logging.getLogger(__name__)

# Terminal task statuses reported by ai-maestro
_DONE_STATUSES = {"completed", "backlog", "failed", "error", "cancelled"}


class WorkflowExecutor:
    """Executes a WorkflowSpec against ai-maestro, monitoring until completion."""

    def __init__(
        self,
        client: MaestroClient,
        poll_interval: float = 5.0,
    ) -> None:
        self._client = client
        self._poll_interval = poll_interval

    async def execute(self, spec: WorkflowSpec) -> WorkflowState:
        """Run a full workflow: provision → assign tasks → monitor → teardown."""
        workflow_id = str(uuid.uuid4())[:8]
        state = WorkflowState(
            workflow_id=workflow_id,
            spec=spec,
            status="pending",
            started_at=_now(),
        )
        logger.info("Starting workflow '%s' (id=%s)", spec.name, workflow_id)

        try:
            state.status = "running"

            # Provision all agents concurrently
            state.created_agents = await self._provision_agents(spec.agents)

            # Create teams and submit tasks (respecting dependencies)
            state.created_teams = await self._create_teams(
                spec.teams, state.created_agents
            )

            # Monitor until all tasks reach a terminal state
            await self._monitor_completion(state)

            state.status = "completed"
            state.completed_at = _now()
            logger.info("Workflow '%s' completed successfully", spec.name)

        except asyncio.CancelledError:
            state.status = "cancelled"
            state.completed_at = _now()
            logger.warning("Workflow '%s' was cancelled", spec.name)
            raise

        except Exception as exc:
            state.status = "failed"
            state.completed_at = _now()
            state.error = str(exc)
            logger.error("Workflow '%s' failed: %s", spec.name, exc)

        finally:
            await self._teardown(state)

        return state

    # === Provisioning ===

    async def _provision_agents(self, agents: list[AgentSpec]) -> dict[str, str]:
        """Create all agents concurrently. Returns {agent_name: maestro_id}."""
        logger.info("Provisioning %d agent(s)...", len(agents))
        tasks = [self._provision_one_agent(agent) for agent in agents]
        results: list[tuple[str, str]] = await asyncio.gather(*tasks)
        id_map = dict(results)
        logger.info("All agents provisioned: %s", id_map)
        return id_map

    async def _provision_one_agent(self, spec: AgentSpec) -> tuple[str, str]:
        """Create a single agent and wake it. Returns (name, maestro_id)."""
        agent_id = await self._client.create_agent(spec)
        logger.debug("Created agent '%s' → id=%s", spec.name, agent_id)
        await self._client.wake_agent(agent_id)
        logger.debug("Woke agent '%s' (id=%s)", spec.name, agent_id)
        return spec.name, agent_id

    # === Team and task creation ===

    async def _create_teams(
        self,
        teams: list[TeamSpec],
        agent_ids: dict[str, str],
    ) -> dict[str, str]:
        """Create all teams and submit tasks respecting dependencies. Returns {team_name: team_id}."""
        team_id_map: dict[str, str] = {}

        for team_spec in teams:
            member_ids = [agent_ids[name] for name in team_spec.agents]
            team_id = await self._client.create_team(team_spec.name, member_ids)
            team_id_map[team_spec.name] = team_id
            logger.info("Created team '%s' → id=%s", team_spec.name, team_id)

            await self._submit_tasks_with_deps(team_id, team_spec, agent_ids)

        return team_id_map

    async def _submit_tasks_with_deps(
        self,
        team_id: str,
        team_spec: TeamSpec,
        agent_ids: dict[str, str],
    ) -> None:
        """Submit tasks in dependency order, waiting for predecessors to finish."""
        submitted: dict[str, str] = {}   # subject → task_id
        completed_subjects: set[str] = set()
        pending = list(team_spec.tasks)

        while pending:
            ready = [
                t for t in pending
                if all(dep in completed_subjects for dep in t.blocked_by)
            ]
            if not ready:
                # Wait for some tasks to complete before continuing
                await asyncio.sleep(self._poll_interval)
                tasks_status = await self._client.get_tasks(team_id)
                for task_status in tasks_status:
                    subject = str(task_status.get("subject", ""))
                    status = str(task_status.get("status", ""))
                    if status == "completed" and subject in submitted:
                        completed_subjects.add(subject)
                continue

            for task_spec in ready:
                blocked_by_ids = [submitted[dep] for dep in task_spec.blocked_by if dep in submitted]
                task_id = await self._client.create_task(team_id, task_spec, blocked_by_ids)
                submitted[task_spec.subject] = task_id
                logger.info(
                    "Submitted task '%s' → id=%s", task_spec.subject, task_id
                )
                pending.remove(task_spec)

    # === Monitoring ===

    async def _monitor_completion(self, state: WorkflowState) -> None:
        """Poll all team tasks until every task reaches a terminal status."""
        logger.info("Monitoring workflow '%s' for completion...", state.spec.name)

        while True:
            all_done = True
            any_failed = False

            for team_name, team_id in state.created_teams.items():
                tasks = await self._client.get_tasks(team_id)
                for task in tasks:
                    status = str(task.get("status", ""))
                    if status not in _DONE_STATUSES:
                        all_done = False
                    if status in {"failed", "error"}:
                        any_failed = True
                        logger.warning(
                            "Task '%s' in team '%s' failed",
                            task.get("subject"),
                            team_name,
                        )

            if all_done:
                if any_failed:
                    raise RuntimeError("One or more tasks failed during workflow execution")
                return

            await asyncio.sleep(self._poll_interval)

    # === Teardown ===

    async def _teardown(self, state: WorkflowState) -> None:
        """Delete agents and teams based on the workflow's teardown policy."""
        policy = state.spec.teardown

        should_teardown = (
            (policy == "on_completion" and state.status == "completed")
            or (policy == "on_failure" and state.status == "failed")
        )

        if not should_teardown:
            logger.info(
                "Teardown skipped (policy=%s, status=%s)", policy, state.status
            )
            return

        logger.info("Running teardown for workflow '%s'...", state.spec.name)

        for name, agent_id in state.created_agents.items():
            try:
                await self._client.delete_agent(agent_id)
                logger.debug("Deleted agent '%s' (id=%s)", name, agent_id)
            except MaestroError as exc:
                logger.warning("Failed to delete agent '%s': %s", name, exc)

        logger.info("Teardown complete")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def run_workflow(spec: WorkflowSpec) -> WorkflowState:
    """Convenience function: create a client from settings and execute a workflow."""
    async with MaestroClient(
        url=settings.maestro_url,
        api_key=settings.maestro_api_key,
    ) as client:
        executor = WorkflowExecutor(client)
        return await executor.execute(spec)
