"""NATS subscriber that signals task terminal states for WorkflowExecutor."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from telemachy.constants import DONE_STATUSES

if TYPE_CHECKING:
    from nats.aio.client import Client as NatsClient
    from nats.aio.msg import Msg

logger = logging.getLogger(__name__)

_SUBJECT_WILDCARD = "hi.tasks.{team_id}.*.*"
_CONNECT_HARD_TIMEOUT = 5.0
_DRAIN_TIMEOUT = 5.0


class NatsUnavailableError(Exception):
    """Raised when NATS cannot be reached or the connection is lost mid-workflow."""


class NatsMonitor:
    """Subscribes to Agamemnon task-lifecycle events; exposes per-task Events.

    Public surface used by WorkflowExecutor:
      __aenter__/__aexit__   — connect/drain lifecycle
      subscribe_team(id)     — register a subscription for one team's task family
      terminal_event(subj)   — get-or-create the asyncio.Event set on terminal status
      latest_status(subj)    — last observed status (or None)
      record_status(subj, s) — monotonic terminal-sticky status writer (single writer)
      notify_submitted()     — call after each successful create_task; wakes dep-wait
      submitted_event        — asyncio.Event the dep-wait loop awaits
      connected              — False if broker disconnected mid-workflow
    """

    def __init__(self, nats_url: str, stop_event: asyncio.Event | None = None) -> None:
        self._nats_url = nats_url
        self._stop_event = stop_event
        self._nc: NatsClient | None = None
        self._broken = asyncio.Event()
        self._events: dict[str, asyncio.Event] = {}
        self._latest_status: dict[str, str] = {}
        self._subs: list[Any] = []
        self.submitted_event = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._nc is not None and not self._nc.is_closed and not self._broken.is_set()

    async def __aenter__(self) -> NatsMonitor:
        # Deferred import so module-import of executor.py does not trigger
        # nats-py's default error logger configuration.
        import nats as _nats

        logging.getLogger("nats").setLevel(logging.CRITICAL)
        try:
            self._nc = await asyncio.wait_for(
                _nats.connect(
                    self._nats_url,
                    allow_reconnect=False,
                    connect_timeout=3,
                    disconnected_cb=self._on_disconnected,
                    closed_cb=self._on_closed,
                ),
                timeout=_CONNECT_HARD_TIMEOUT,
            )
        except Exception as exc:
            raise NatsUnavailableError(
                f"failed to connect to NATS at {self._nats_url}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._nc is not None and not self._nc.is_closed:
            try:
                await asyncio.wait_for(self._nc.drain(), timeout=_DRAIN_TIMEOUT)
            except Exception as exc:
                logger.warning("NATS drain failed: %s", exc)
        self._nc = None

    async def subscribe_team(self, team_id: str) -> None:
        if self._nc is None:
            raise RuntimeError("NatsMonitor not connected")
        subject = _SUBJECT_WILDCARD.format(team_id=team_id)
        sub = await self._nc.subscribe(subject, cb=self._handle_msg)
        self._subs.append(sub)
        logger.debug("Subscribed to %s", subject)

    def terminal_event(self, task_subject: str) -> asyncio.Event:
        ev = self._events.get(task_subject)
        if ev is None:
            ev = asyncio.Event()
            self._events[task_subject] = ev
        return ev

    def latest_status(self, task_subject: str) -> str | None:
        return self._latest_status.get(task_subject)

    def record_status(self, task_subject: str, status: str) -> None:
        """Monotonic terminal-sticky status writer (single writer in asyncio loop).

        Terminal status is sticky: once set, a later non-terminal update cannot
        overwrite it. No `await` in the body, so safe under single-loop asyncio.
        """
        if not task_subject:
            return
        prev = self._latest_status.get(task_subject)
        if prev in DONE_STATUSES and status not in DONE_STATUSES:
            return
        self._latest_status[task_subject] = status
        if status in DONE_STATUSES:
            self.terminal_event(task_subject).set()

    def notify_submitted(self) -> None:
        """Wake any coroutine waiting in `submitted_event.wait()`."""
        self.submitted_event.set()
        # Immediately clear so the next call cleanly re-wakes.
        self.submitted_event.clear()

    async def _handle_msg(self, msg: Msg) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            logger.warning("malformed NATS payload on %s: %r", msg.subject, msg.data[:200])
            return
        data = payload.get("data", {})
        if not isinstance(data, dict):
            logger.warning("unexpected NATS envelope on %s: %r", msg.subject, payload)
            return
        task_subject = str(data.get("subject", ""))
        if not task_subject:
            logger.warning(
                "NATS event on %s has no data.subject; first 200 bytes: %r",
                msg.subject,
                msg.data[:200],
            )
            return
        verb = msg.subject.rsplit(".", 1)[-1]
        status = str(data.get("status", verb))
        self.record_status(task_subject, status)

    async def _on_disconnected(self) -> None:
        logger.warning("NATS disconnected from %s", self._nats_url)
        self._broken.set()

    async def _on_closed(self) -> None:
        logger.warning("NATS connection closed for %s", self._nats_url)
        self._broken.set()
