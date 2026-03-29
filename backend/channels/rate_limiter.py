"""
Per-user token bucket rate limiter.
Default: 1 request per 3 seconds per user.
"""
from __future__ import annotations
import time


class RateLimiter:
    def __init__(self, rate_seconds: float = 3.0) -> None:
        self._rate = rate_seconds
        self._last: dict[str, float] = {}

    def check(self, user_key: str) -> bool:
        """
        Returns True if the user is allowed to proceed.
        Returns False if they're within the rate window (too fast).
        """
        now = time.monotonic()
        last = self._last.get(user_key, 0.0)
        if now - last < self._rate:
            return False
        self._last[user_key] = now
        return True

    def reset(self, user_key: str) -> None:
        self._last.pop(user_key, None)
