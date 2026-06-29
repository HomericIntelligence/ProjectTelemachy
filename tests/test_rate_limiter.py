"""Tests for the TokenBucket rate limiter (#160).

Timing windows are intentionally wide to absorb event-loop variance on CI.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from telemachy.rate_limiter import TokenBucket


def test_burst_zero_raises() -> None:
    with pytest.raises(ValueError, match="burst must be >= 1"):
        TokenBucket(rate=5.0, burst=0)


def test_burst_negative_raises() -> None:
    with pytest.raises(ValueError, match="burst must be >= 1"):
        TokenBucket(rate=5.0, burst=-3)


def test_disabled_when_rate_zero() -> None:
    bucket = TokenBucket(rate=0.0, burst=1)
    assert not bucket.enabled


def test_disabled_when_rate_negative() -> None:
    bucket = TokenBucket(rate=-1.0, burst=1)
    assert not bucket.enabled


@pytest.mark.asyncio
async def test_disabled_rate_returns_immediately() -> None:
    bucket = TokenBucket(rate=0.0, burst=1)
    start = time.monotonic()
    for _ in range(1000):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_burst_consumed_then_throttled() -> None:
    """3 tokens fire instantly; 4th waits ~0.2s at 5 RPS.

    Wide [0.12, 0.8] window absorbs CI event-loop variance.
    """
    bucket = TokenBucket(rate=5.0, burst=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - start < 0.10  # burst should be near-instant
    await bucket.acquire()
    total = time.monotonic() - start
    assert 0.12 <= total <= 0.8  # ±60% around 0.2s


@pytest.mark.asyncio
async def test_refill_caps_at_burst() -> None:
    """After a long idle period, tokens cap at burst — no infinite accrual."""
    bucket = TokenBucket(rate=100.0, burst=2)
    await bucket.acquire()
    await bucket.acquire()
    await asyncio.sleep(0.2)  # would refill 20 tokens but cap=2
    start = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()  # 3rd waits ~0.01s
    assert time.monotonic() - start >= 0.005
