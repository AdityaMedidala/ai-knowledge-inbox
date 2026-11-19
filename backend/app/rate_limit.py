"""In-memory, per-client sliding-window limits for the public demo (DEMO_MODE=on).

Single process only: limits reset on restart and are not shared between replicas, which is
enough for one small demo container (see README "Known limitations").
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.domain.errors import AppError, ErrorCode

WINDOW_S = 3600.0


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_s: float = WINDOW_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def acquire(self, key: str) -> float | None:
        """Record a hit and return None, or return the seconds until the next one is allowed."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self._window_s:
                hits.popleft()
            if len(hits) >= self._limit:
                return hits[0] + self._window_s - now
            hits.append(now)
            if len(self._hits) > 10_000:  # drop idle clients so memory stays bounded
                self._hits = {
                    k: v for k, v in self._hits.items() if v and v[-1] > now - self._window_s
                }
            return None


def rate_limit(action: str, noun: str) -> Callable[[Request], None]:
    """FastAPI dependency; a no-op unless the app registered a limiter for `action`."""

    def dependency(request: Request) -> None:
        limiter: SlidingWindowLimiter | None = request.app.state.rate_limits.get(action)
        if limiter is None:
            return
        client = request.client.host if request.client else "unknown"
        wait_s = limiter.acquire(client)
        if wait_s is not None:
            minutes = max(1, math.ceil(wait_s / 60))
            raise AppError(
                ErrorCode.RATE_LIMITED,
                f"This demo allows {limiter.limit} {noun} per hour from one address. "
                f"Try again in {minutes} min.",
                {"retry_after_s": math.ceil(wait_s), "limit_per_hour": limiter.limit},
            )

    return dependency
