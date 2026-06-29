"""Shared constants for the telemachy package.

Kept in its own module so both executor.py and nats_monitor.py can import
these without creating a circular dependency.
"""

from __future__ import annotations

# Terminal task statuses reported by ProjectAgamemnon. "backlog" is an
# initial/queued state, NOT a terminal state — do not include it here.
DONE_STATUSES: frozenset[str] = frozenset({"completed", "failed", "error", "cancelled"})
"""Task statuses that indicate a task has reached a terminal state.

A task in any of these statuses will not transition further. The set is
frozen so callers cannot mutate the canonical definition.
"""
