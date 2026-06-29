"""Async token-bucket rate limiter for outbound Agamemnon HTTP calls (#160).

Design draws on the `gh-cli-proactive-per-thread-throttle` pattern: throttle
at a single chokepoint, proactive cap before requests leave the process.
Uses `time.monotonic()` (clock-jump safe). asyncio.Lock() is safe at
construction time because Telemachy targets Python >= 3.10.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Async token bucket: refills at `rate` tokens/sec, capped at `burst`.

    A zero or negative `rate` disables throttling (acquire() is a no-op).
    `burst` must be >= 1; ValueError on construction otherwise.
    """

    def __init__(self, rate: float, burst: int) -> None:
        if burst < 1:
            raise ValueError(f"burst must be >= 1, got {burst}")
        self._rate = float(rate)
        self._capacity = float(burst)
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._rate > 0.0

    async def acquire(self, n: float = 1.0) -> None:
        if not self.enabled:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                await asyncio.sleep(deficit / self._rate)
