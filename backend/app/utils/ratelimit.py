"""In-process sliding-window rate limiter (single-instance deployments).

For multi-instance deployments replace with a shared store (e.g. Redis); the
OTP attempt / resend limits themselves are persisted in MongoDB and are
enforced regardless of instance count.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from backend.app.utils.errors import APIError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: float) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(window_s - (now - q[0])) + 1
            raise APIError(429, "rate_limited", "Too many requests. Please try again later.", {"retry_after_s": retry})
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()
