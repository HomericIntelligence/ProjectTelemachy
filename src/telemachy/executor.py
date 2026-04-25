"""WorkflowExecutor: orchestrates the full workflow lifecycle via ProjectAgamemnon."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from telemachy.config import settings
from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.models import AgentSpec, TeamSpec, WorkflowSpec, WorkflowState

logger = logging.getLogger(__name__)

# Terminal task statuses reported by ProjectAgamemnon
# NOTE: "backlog" is an initial/queued state, NOT a terminal state — do not include it here.
_DONE_STATUSES = {"completed", "failed", "error", "cancelled"}


class WorkflowTimeoutError(Exception):
    """Raised when workflow monitoring exceeds the configured timeout or max poll count."""


class WorkflowExecutor:
    """Executes a WorkflowSpec against Agamemnon, monitoring until completion."""

    def __init__(
        self,
        client: AgamemnonClient,
        poll_interval: float = 5.0,
    ) -> None:
        self._client = client
        self._poll_interval = poll_interval

    async def execute(self, spec: WorkflowSpec) -> WorkflowState:
        """Run a full workflow: provision → assign tasks → monitor → teardown."""
        timeout = spec.timeout_seconds if spec.timeout_seconds is not None else settings.default_workflow_timeout
        try:
            return await asyncio.wait_for(self._run(spec), timeout=timeout)
        except asyncio.TimeoutError:
            raise WorkflowTimeoutError(
                f"Workflow '{spec.name}' exceeded its execution timeout of {timeout}s"
            )

    async def _run(self, spec: WorkflowSpec) -> WorkflowState:
        """Internal execution body — wrapped by execute() with a timeout."""
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
        """Create all agents concurrently. Returns {agent_name: agamemnon_id}."""
        logger.info("Provisioning %d agent(s)...", len(agents))
        tasks = [self._provision_one_agent(agent) for agent in agents]
        results: list[tuple[str, str]] = await asyncio.gather(*tasks)
        id_map = dict(results)
        logger.info("All agents provisioned: %s", id_map)
        return id_map

    async def _provision_one_agent(self, spec: AgentSpec) -> tuple[str, str]:
        """Create a single agent and wake it. Returns (name, agamemnon_id)."""
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
        """Create all teams concurrently and submit tasks respecting dependencies.

        Teams are provisioned in parallel via asyncio.gather (see #55).
        Returns {team_name: team_id}.
        """
        results: list[tuple[str, str]] = await asyncio.gather(
            *[self._create_team(team_spec, agent_ids) for team_spec in teams]
        )
        return dict(results)

    async def _create_team(
        self,
        team_spec: TeamSpec,
        agent_ids: dict[str, str],
    ) -> tuple[str, str]:
        """Create a single team, submit its tasks, and return (team_name, team_id)."""
        member_ids = [agent_ids[name] for name in team_spec.agents]
        team_id = await self._client.create_team(team_spec.name, member_ids)
        logger.info("Created team '%s' → id=%s", team_spec.name, team_id)
        await self._submit_tasks_with_deps(team_id, team_spec, agent_ids)
        return team_spec.name, team_id

    async def _submit_tasks_with_deps(
        self,
        team_id: str,
        team_spec: TeamSpec,
        agent_ids: dict[str, str],
    ) -> None:
        """Submit tasks in dependency order, waiting for predecessors to finish.

        If a dependency has failed/errored/cancelled, the dependent task is skipped
        rather than waiting forever (prevents infinite loop — see #13).
        """
        submitted: dict[str, str] = {}   # subject → task_id
        completed_subjects: set[str] = set()
        failed_subjects: set[str] = set()
        skipped_subjects: set[str] = set()
        pending = list(team_spec.tasks)

        while pending:
            # Skip tasks whose dependencies have failed
            newly_skipped = [
                t for t in pending
                if any(dep in failed_subjects or dep in skipped_subjects for dep in t.blocked_by)
            ]
            for task_spec in newly_skipped:
                logger.warning(
                    "Skipping task '%s': one or more dependencies failed or were skipped",
                    task_spec.subject,
                )
                skipped_subjects.add(task_spec.subject)
                pending.remove(task_spec)

            ready = [
                t for t in pending
                if all(dep in completed_subjects for dep in t.blocked_by)
            ]
            if not ready:
                if not pending:
                    break
                # Wait for some tasks to complete before continuing
                await asyncio.sleep(self._poll_interval)
                tasks_status = await self._client.get_tasks(team_id)
                for task_status in tasks_status:
                    subject = str(task_status.get("subject", ""))
                    status = str(task_status.get("status", ""))
                    if subject in submitted:
                        if status == "completed":
                            completed_subjects.add(subject)
                        elif status in {"failed", "error", "cancelled"}:
                            failed_subjects.add(subject)
                continue

            for task_spec in ready:
                blocked_by_ids = [submitted[dep] for dep in task_spec.blocked_by if dep in submitted]
                # Resolve agent name → Agamemnon agent ID before submitting (#12)
                resolved_agent_id: str | None = None
                if task_spec.assign_to:
                    resolved_agent_id = agent_ids.get(task_spec.assign_to)
                task_id = await self._client.create_task(
                    team_id, task_spec, blocked_by_ids, assignee_agent_id=resolved_agent_id
                )
                submitted[task_spec.subject] = task_id
                logger.info(
                    "Submitted task '%s' → id=%s", task_spec.subject, task_id
                )
                pending.remove(task_spec)

    # === Monitoring ===

    async def _monitor_completion(self, state: WorkflowState) -> None:
        """Poll all team tasks until every task reaches a terminal status."""
        logger.info("Monitoring workflow '%s' for completion...", state.spec.name)

        poll_count = 0
        start_time = time.monotonic()
        timeout = settings.monitor_timeout_seconds
        max_polls = settings.monitor_max_polls

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                raise WorkflowTimeoutError(
                    f"Monitoring timed out after {elapsed:.1f}s "
                    f"(limit: {timeout}s) for workflow '{state.spec.name}'"
                )
            if poll_count > max_polls:
                raise WorkflowTimeoutError(
                    f"Monitoring exceeded max poll count {max_polls} "
                    f"for workflow '{state.spec.name}'"
                )

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

            poll_count += 1
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

        for name, team_id in state.created_teams.items():
            try:
                await self._client.delete_team(team_id)
                logger.debug("Deleted team '%s' (id=%s)", name, team_id)
            except AgamemnonError as exc:
                logger.warning("Failed to delete team '%s': %s", name, exc)

        for name, agent_id in state.created_agents.items():
            try:
                await self._client.delete_agent(agent_id)
                logger.debug("Deleted agent '%s' (id=%s)", name, agent_id)
            except AgamemnonError as exc:
                logger.warning("Failed to delete agent '%s': %s", name, exc)

        logger.info("Teardown complete")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def run_workflow(spec: WorkflowSpec) -> WorkflowState:
    """Convenience function: create a client from settings and execute a workflow."""
    async with AgamemnonClient(
        url=settings.agamemnon_url,
        api_key=settings.agamemnon_api_key,
        host_id=settings.host_id,
        require_tls=settings.require_tls,
        nats_url=settings.nats_url,
    ) as client:
        executor = WorkflowExecutor(client)
        return await executor.execute(spec)
