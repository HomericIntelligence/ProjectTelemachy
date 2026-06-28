"""Deterministic idempotency keys for Telemachy-managed Agamemnon resources."""

from __future__ import annotations

import hashlib
import re

_KEY_PREFIX = "tlm-"
_HASH_LEN = 16  # 64 bits — collision-safe within a single workflow's namespace
_NAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def make_key(workflow_name: str, resource_name: str) -> str:
    """Return a stable idempotency key for one workflow resource.

    Format: ``tlm-<16 hex chars>-<sanitised resource name>``. The hash is the
    match key; the trailing readable name aids ``agamemnon agents list``.
    """
    digest = hashlib.sha256(f"{workflow_name}|{resource_name}".encode()).hexdigest()[:_HASH_LEN]
    suffix = _NAME_SAFE.sub("-", resource_name)[:40]
    return f"{_KEY_PREFIX}{digest}-{suffix}"


def is_telemachy_key(name: str) -> bool:
    """True iff *name* was produced by :func:`make_key` (used by ``check``)."""
    return name.startswith(_KEY_PREFIX)
