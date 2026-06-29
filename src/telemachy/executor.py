"""WorkflowExecutor: orchestrates the full workflow lifecycle via ProjectAgamemnon."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.config import settings
from telemachy.models import AgentSpec, TeamSpec, WorkflowSpec, WorkflowState

logger = logging.getLogger(__name__)

# Terminal task statuses reported by ProjectAgamemnon
# NOTE: "backlog" is an initial/queued state, NOT a terminal state — do not include it here.
_DONE_STATUSES = {"completed", "failed", "error", "cancelled"}


class WorkflowTimeoutError(Exception):
    """Raised when workflow monitoring exceeds the configured timeout or max poll count."""


class WorkflowConnectivityError(Exception):
    """Raised when Agamemnon fails consecutive heartbeat probes during monitoring."""


class WorkflowExecutor:
    """Executes a WorkflowSpec against Agamemnon, monitoring until completion."""

    def __init__(
        self,
        client: AgamemnonClient,
        poll_interval: float = 5.0,
        dry_run: bool = False,
        stop_event: asyncio.Event | None = None,
        max_concurrent_provisioning: int = 16,
        force: bool = False,
        existing_snapshot: tuple[list[dict[str, object]], list[dict[str, object]]] | None = None,
    ) -> None:
        self._client = client
        self._poll_interval = poll_interval
        self._dry_run = dry_run
        self._stop_event = stop_event
        # Bound concurrent agent-provisioning fan-out so a workflow with many
        # agents does not overwhelm Agamemnon (#166). Default 16 matches
        # typical small-fleet sizing; callers can raise/lower as needed.
        self._provision_semaphore = asyncio.Semaphore(max(1, max_concurrent_provisioning))
        self._force = force
        # If the caller already fetched list_agents()/list_teams() (e.g. cli.run for
        # the --force warning), reuse that snapshot to avoid a second API round-trip.
        self._injected_snapshot = existing_snapshot
        self._existing_agents_by_key: dict[str, str] = {}
        self._existing_teams_by_key: dict[str, str] = {}
        self._hooks: dict[str, list[Callable[..., Any]]] = {
            "on_task_complete": [],
            "on_task_failed": [],
            "on_workflow_complete": [],
            "on_workflow_failed": [],
        }

    def add_hook(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a callback for a workflow execution event.

        Supported events: on_task_complete, on_task_failed,
        on_workflow_complete, on_workflow_failed.
        """
        if event not in self._hooks:
            raise ValueError(f"Unknown hook event {event!r}. Valid events: {sorted(self._hooks)}")
        self._hooks[event].append(callback)

    async def _emit(self, event: str, **kwargs: Any) -> None:
        """Fire all callbacks registered for *event*."""
        for cb in self._hooks.get(event, []):
            if inspect.iscoroutinefunction(cb):
                await cb(**kwargs)
            else:
                cb(**kwargs)

    async def execute(self, spec: WorkflowSpec) -> WorkflowState:
        """Run a full workflow: provision → assign tasks → monitor → teardown."""
        # Emitted-event subjects are scoped to each monitor session (local set
        # in _monitor_completion), so no per-execution instance reset is needed
        # — reusing the same executor cannot leak prior-run subjects (#162/#203).
        timeout = (
            spec.timeout_seconds
            if spec.timeout_seconds is not None
            else settings.default_workflow_timeout
        )
        try:
            return await asyncio.wait_for(self._run(spec), timeout=timeout)
        except TimeoutError as exc:
            raise WorkflowTimeoutError(
                f"Workflow '{spec.name}' exceeded its execution timeout of {timeout}s"
            ) from exc

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

            # Populate idempotency lookup tables (skipped on dry-run or force).
            if not self._dry_run and not self._force:
                if self._injected_snapshot is not None:
                    agents_snapshot, teams_snapshot = self._injected_snapshot
                else:
                    agents_snapshot = await self._client.list_agents()
                    teams_snapshot = await self._client.list_teams()
                self._existing_agents_by_key = {
                    str(a.get("name", "")): str(a.get("id", ""))
                    for a in agents_snapshot
                    if a.get("name") and a.get("id")
                }
                self._existing_teams_by_key = {
                    str(t.get("name", "")): str(t.get("id", ""))
                    for t in teams_snapshot
                    if t.get("name") and t.get("id")
                }

            # Provision all agents concurrently. _provision_agents aliases its
            # internal id_map to state.created_agents up front so teardown sees
            # every successfully-created agent even on partial failure (#164).
            await self._provision_agents(spec.agents, spec.name, state)

            # Create teams and submit tasks (respecting dependencies)
            state.created_teams = await self._create_teams(
                spec.teams, state.created_agents, spec.name
            )

            # Monitor until all tasks reach a terminal state (skipped in dry-run)
            if not self._dry_run:
                await self._monitor_completion(state)
            else:
                logger.info("[dry-run] Skipping monitoring — no real tasks submitted")

            if state.status == "cancelled":
                # Graceful stop-event cancellation — monitor returned early.
                state.completed_at = _now()
                logger.warning("Workflow '%s' was cancelled via stop event", spec.name)
            else:
                state.status = "completed"
                state.completed_at = _now()
                logger.info("Workflow '%s' completed successfully", spec.name)
                await self._emit("on_workflow_complete", state=state)

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
            await self._emit("on_workflow_failed", state=state, error=exc)

        finally:
            await self._teardown(state)

        return state

    # === Provisioning ===

    async def _provision_agents(
        self,
        agents: list[AgentSpec],
        workflow_name: str,
        state: WorkflowState,
    ) -> dict[str, str]:
        """Create all agents concurrently. Returns {agent_name: agamemnon_id}.

        The returned dict is also aliased to state.created_agents up front and
        mutated incrementally: each per-agent coroutine records its id the moment
        create_agent returns, BEFORE wake_agent runs, so teardown sees every
        created agent even if wake_agent or a sibling coroutine fails (#164).
        """
        logger.info("Provisioning %d agent(s)...", len(agents))

        # Shared id map — mutated by _provision_one_agent the instant each
        # create_agent call returns. Aliased to state.created_agents so teardown
        # sees newly-created agents even if the workflow raises mid-fan-out (#164).
        id_map: dict[str, str] = {}
        state.created_agents = id_map

        async def _bounded(agent: AgentSpec) -> tuple[str, str]:
            async with self._provision_semaphore:
                return await self._provision_one_agent(agent, workflow_name, id_map)

        coros = [_bounded(agent) for agent in agents]
        raw_results: list[tuple[str, str] | BaseException] = await asyncio.gather(
            *coros, return_exceptions=True
        )
        first_exc: BaseException | None = next(
            (r for r in raw_results if isinstance(r, BaseException)), None
        )
        if first_exc is not None:
            raise first_exc
        logger.info("All agents provisioned: %s", id_map)
        return id_map

    async def _provision_one_agent(
        self,
        spec: AgentSpec,
        workflow_name: str,
        id_map: dict[str, str],
    ) -> tuple[str, str]:
        """Create a single agent and wake it. Returns (name, agamemnon_id).

        If an agent with this workflow's idempotency key already exists, reuse it.

        Mutates *id_map* as a side effect: the Agamemnon id is recorded the
        moment create_agent (or reuse) resolves — BEFORE wake_agent is awaited —
        so a wake failure does not leave an orphan agent untracked by teardown
        (#164). This is safe under asyncio's cooperative single-threaded
        scheduling: the assignment is between two await points and cannot
        interleave with other coroutines. Agent-name collisions are
        prevented by WorkflowSpec.validate_unique_agent_names.
        """
        from telemachy.idempotency import make_key


        if self._dry_run:
            dry_id = f"dry-run-agent-{spec.name}"
            id_map[spec.name] = dry_id
            logger.info("[dry-run] Would create agent '%s' → id=%s", spec.name, dry_id)
            return spec.name, dry_id

        key = make_key(workflow_name, spec.name)
        existing_id = self._existing_agents_by_key.get(key)
        if existing_id and not self._force:
            # Record the reused id BEFORE waking it, so a wake failure does not
            # leave the (reused) agent untracked by teardown (#164).
            id_map[spec.name] = existing_id
            logger.info(
                "Reusing existing agent '%s' (id=%s, key=%s)",
                spec.name,
                existing_id,
                key,
            )
            # The reused agent may already be running. wake_agent maps to
            # POST /v1/agents/{id}/start; tolerate already-running responses by
            # swallowing only conflict-shaped AgamemnonError (status 409, or 400
            # with a recognisable message). Anything else re-raises.
            try:
                await self._client.wake_agent(existing_id)
            except AgamemnonError as exc:
                already_running = exc.status_code == 409 or (
                    exc.status_code == 400 and "running" in str(exc).lower()
                )
                if not already_running:
                    raise
                logger.info(
                    "Agent '%s' (id=%s) was already running; reuse continues",
                    spec.name,
                    existing_id,
                )
            return spec.name, existing_id

        agent_id = await self._client.create_agent(spec, idempotency_name=key)
        # Record the id BEFORE any further awaitable that could fail (#164).
        id_map[spec.name] = agent_id
        logger.debug("Created agent '%s' → id=%s (key=%s)", spec.name, agent_id, key)
        await self._client.wake_agent(agent_id)
        logger.debug("Woke agent '%s' (id=%s)", spec.name, agent_id)
        return spec.name, agent_id

    # === Team and task creation ===

    async def _create_teams(
        self,
        teams: list[TeamSpec],
        agent_ids: dict[str, str],
        workflow_name: str,
    ) -> dict[str, str]:
        """Create all teams concurrently and submit tasks respecting dependencies.

        Teams are provisioned in parallel via asyncio.gather (see #55).
        Returns {team_name: team_id}.
        """
        results: list[tuple[str, str]] = await asyncio.gather(
            *[self._create_team(team_spec, agent_ids, workflow_name) for team_spec in teams]
        )
        return dict(results)

    async def _create_team(
        self,
        team_spec: TeamSpec,
        agent_ids: dict[str, str],
        workflow_name: str,
    ) -> tuple[str, str]:
        """Create a single team, submit its tasks, and return (team_name, team_id)."""
        from telemachy.idempotency import make_key

        if self._dry_run:
            dry_id = f"dry-run-team-{team_spec.name}"
            logger.info("[dry-run] Would create team '%s' → id=%s", team_spec.name, dry_id)
            for task_spec in team_spec.tasks:
                logger.info(
                    "[dry-run] Would submit task '%s' (assign_to=%s, blocked_by=%s)",
                    task_spec.subject,
                    task_spec.assign_to,
                    task_spec.blocked_by,
                )
            return team_spec.name, dry_id

        member_ids = [agent_ids[name] for name in team_spec.agents]
        key = make_key(workflow_name, team_spec.name)
        existing_id = self._existing_teams_by_key.get(key)
        if existing_id and not self._force:
            logger.info(
                "Reusing existing team '%s' (id=%s, key=%s); membership not reconciled",
                team_spec.name,
                existing_id,
                key,
            )
            team_id = existing_id
        else:
            team_id = await self._client.create_team(key, member_ids)
            logger.info("Created team '%s' → id=%s (key=%s)", team_spec.name, team_id, key)
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
        submitted: dict[str, str] = {}  # subject → task_id
        completed_subjects: set[str] = set()
        failed_subjects: set[str] = set()
        skipped_subjects: set[str] = set()

        if not self._force:
            existing = await self._client.get_tasks(team_id)
            for t in existing:
                subj = str(t.get("subject", ""))
                tid = str(t.get("id", ""))
                status = str(t.get("status", ""))
                if subj and tid:
                    submitted[subj] = tid
                    if status == "completed":
                        completed_subjects.add(subj)
                    elif status in {"failed", "error", "cancelled"}:
                        failed_subjects.add(subj)
            if submitted:
                logger.info(
                    "Reusing %d existing task(s) in team %s", len(submitted), team_spec.name
                )

        pending = [t for t in team_spec.tasks if t.subject not in submitted]

        while pending:
            # Skip tasks whose dependencies have failed
            newly_skipped = [
                t
                for t in pending
                if any(dep in failed_subjects or dep in skipped_subjects for dep in t.blocked_by)
            ]
            for task_spec in newly_skipped:
                logger.warning(
                    "Skipping task '%s': a dependency failed or was skipped (%s)",
                    task_spec.subject,
                    [
                        dep
                        for dep in task_spec.blocked_by
                        if dep in failed_subjects or dep in skipped_subjects
                    ],
                )
                skipped_subjects.add(task_spec.subject)
                pending.remove(task_spec)

            ready = [t for t in pending if all(dep in completed_subjects for dep in t.blocked_by)]
            if not ready:
                if not pending:
                    break
                if self._stop_event and self._stop_event.is_set():
                    logger.warning("Stop event set — aborting task submission")
                    raise asyncio.CancelledError("Task submission cancelled by stop event")
                # Wait for some tasks to complete before continuing
                await asyncio.sleep(self._poll_interval)
                tasks_status = await self._client.get_tasks(team_id)
                for task_status in tasks_status:
                    subject = str(task_status.get("subject", ""))
                    status = str(task_status.get("status", ""))
                    if status == "completed" and subject in submitted:
                        completed_subjects.add(subject)
                    elif status in {"failed", "error", "cancelled"} and subject in submitted:
                        failed_subjects.add(subject)
                continue

            for task_spec in ready:
                blocked_by_ids = [
                    submitted[dep] for dep in task_spec.blocked_by if dep in submitted
                ]
                # Resolve agent name → Agamemnon agent ID before submitting (#12)
                resolved_agent_id: str | None = None
                if task_spec.assign_to:
                    resolved_agent_id = agent_ids.get(task_spec.assign_to)
                task_id = await self._client.create_task(
                    team_id, task_spec, blocked_by_ids, assignee_agent_id=resolved_agent_id
                )
                submitted[task_spec.subject] = task_id
                logger.info("Submitted task '%s' → id=%s", task_spec.subject, task_id)
                pending.remove(task_spec)

    # === Monitoring ===

    async def _monitor_completion(self, state: WorkflowState) -> None:
        """Poll all team tasks until every task reaches a terminal status.

        The set of subjects for which we've already emitted a terminal-state
        callback is scoped to this single monitoring session (#162) — invoking
        _monitor_completion again starts with a fresh set, so duplicate task
        subjects across separate runs each get their callbacks.

        Runs a background heartbeat task to detect Agamemnon connectivity loss
        mid-workflow. If connectivity is lost, raises WorkflowConnectivityError
        which sets state.connectivity_failed for teardown.
        """
        logger.info("Monitoring workflow '%s' for completion...", state.spec.name)
        connectivity_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(state.spec.name, connectivity_lost),
            name=f"telemachy-heartbeat-{state.workflow_id}",
        )
        try:
            await self._poll_until_done(state, connectivity_lost)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, workflow_name: str, connectivity_lost: asyncio.Event) -> None:
        """Background task that probes Agamemnon liveness on a timer.

        Calls ping() every healthcheck_interval_seconds and sets connectivity_lost
        after healthcheck_failure_threshold consecutive failures.
        """
        interval = settings.healthcheck_interval_seconds
        threshold = settings.healthcheck_failure_threshold
        timeout = settings.healthcheck_timeout_seconds
        consecutive_failures = 0
        while not connectivity_lost.is_set():
            await asyncio.sleep(interval)
            ok = await self._client.ping(timeout=timeout)
            if ok:
                if consecutive_failures:
                    logger.info(
                        "Agamemnon connectivity restored for workflow '%s' after %d failure(s)",
                        workflow_name,
                        consecutive_failures,
                    )
                consecutive_failures = 0
                continue
            consecutive_failures += 1
            logger.warning(
                "Agamemnon health check failed (%d/%d) for workflow '%s'",
                consecutive_failures,
                threshold,
                workflow_name,
            )
            if consecutive_failures >= threshold:
                connectivity_lost.set()
                return

    async def _poll_until_done(
        self, state: WorkflowState, connectivity_lost: asyncio.Event
    ) -> None:
        """Poll all team tasks until every task reaches a terminal status.

        Checks the connectivity_lost event at the start of each iteration and
        raises WorkflowConnectivityError if it is set, storing the failure flag
        on state so _teardown can honour it under on_completion policy.
        """
        poll_count = 0
        start_time = time.monotonic()
        timeout = settings.monitor_timeout_seconds
        max_polls = settings.monitor_max_polls
        emitted_done: set[str] = set()

        while True:
            if connectivity_lost.is_set():
                state.connectivity_failed = True
                raise WorkflowConnectivityError(
                    f"Agamemnon failed {settings.healthcheck_failure_threshold} "
                    f"consecutive health checks for workflow '{state.spec.name}'"
                )
            if self._stop_event and self._stop_event.is_set():
                logger.warning(
                    "Stop event set — aborting monitoring for workflow '%s'",
                    state.spec.name,
                )
                state.status = "cancelled"
                return

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
                    task_subject = str(task.get("subject", ""))
                    if status not in _DONE_STATUSES:
                        all_done = False
                    if status in {"failed", "error"}:
                        any_failed = True
                        logger.warning(
                            "Task '%s' in team '%s' failed",
                            task_subject,
                            team_name,
                        )
                        if task_subject not in emitted_done:
                            emitted_done.add(task_subject)
                            await self._emit("on_task_failed", task=task, team=team_name)
                    elif status == "completed" and task_subject not in emitted_done:
                        emitted_done.add(task_subject)
                        await self._emit("on_task_complete", task=task, team=team_name)

            if all_done:
                if any_failed:
                    raise RuntimeError("One or more tasks failed during workflow execution")
                return

            poll_count += 1
            await asyncio.sleep(self._poll_interval)

    # === Teardown ===

    async def _teardown(self, state: WorkflowState) -> None:
        """Delete agents and teams based on the workflow's teardown policy."""
        if self._dry_run:
            logger.info("[dry-run] Skipping teardown")
            return

        policy = state.spec.teardown

        # A connectivity-induced failure should still honour an `on_completion`
        # policy — the workflow author asked us to clean up after this workflow,
        # and "Agamemnon went away mid-run" should not leak agents and teams
        # (see #161). We do NOT extend on_completion to *task* failures, which
        # are the existing "leave for inspection" behaviour.
        should_teardown = (
            (policy == "on_completion" and state.status == "completed")
            or (policy == "on_completion" and state.connectivity_failed)
            or (policy == "on_failure" and state.status == "failed")
        )

        if not should_teardown:
            logger.info("Teardown skipped (policy=%s, status=%s)", policy, state.status)
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
    return datetime.now(tz=UTC).isoformat()


async def run_workflow(
    spec: WorkflowSpec,
    dry_run: bool = False,
    stop_event: asyncio.Event | None = None,
    force: bool = False,
) -> WorkflowState:
    """Convenience function: create a client from settings and execute a workflow."""
    async with AgamemnonClient(**settings.client_kwargs()) as client:
        executor = WorkflowExecutor(
            client,
            dry_run=dry_run,
            stop_event=stop_event,
            force=force,
        )
        return await executor.execute(spec)
