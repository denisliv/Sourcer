"""
Rate limiter for LinkedIn API requests.

Sliding-window algorithm with jitter to mimic human browsing patterns
and avoid being flagged by LinkedIn's anti-bot detection.
"""

import logging
import random
import time
from collections import deque
from threading import Lock
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter with burst detection."""

    WINDOW_SIZE_SECONDS = 60.0
    BURST_DETECTION_WINDOW_SECONDS = 10.0
    FIRST_REQUEST_DELAY_MULTIPLIER = 0.5
    BURST_JITTER_MULTIPLIER = 0.5
    NORMAL_JITTER_MIN = -0.5
    NORMAL_JITTER_MAX = 1.5

    def __init__(
        self,
        requests_per_minute: int = 10,
        min_delay_seconds: float = 3.0,
        max_delay_seconds: float = 8.0,
        burst_size: int = 3,
    ):
        self.requests_per_minute = requests_per_minute
        self.min_delay = min_delay_seconds
        self.max_delay = max_delay_seconds
        self.burst_size = burst_size

        self.request_times: Deque[float] = deque()
        self.last_request_time: Optional[float] = None
        self.lock = Lock()

        logger.info(
            "Rate limiter: %d req/min, delay %.1f-%.1fs, burst %d",
            requests_per_minute, min_delay_seconds, max_delay_seconds, burst_size,
        )

    def wait(self) -> float:
        """Block until it is safe to make the next request. Returns actual delay."""
        with self.lock:
            now = time.time()
            self._cleanup(now)
            delay = self._calculate_delay(now)
            delay = self._enforce_rate_limit(now, delay)
            if delay > 0:
                logger.debug("Rate limiter: sleeping %.2fs", delay)
                time.sleep(delay)
            actual = time.time()
            self.request_times.append(actual)
            self.last_request_time = actual
            return delay

    # ── internals ────────────────────────────────────────────────

    def _cleanup(self, now: float) -> None:
        while self.request_times and now - self.request_times[0] > self.WINDOW_SIZE_SECONDS:
            self.request_times.popleft()

    def _count_recent(self, now: float, window: float) -> int:
        return sum(1 for t in self.request_times if now - t < window)

    def _enforce_rate_limit(self, now: float, base: float) -> float:
        if len(self.request_times) >= self.requests_per_minute:
            oldest = self.request_times[0]
            wait = self.WINDOW_SIZE_SECONDS - (now - oldest)
            if wait > 0:
                logger.warning("Rate limit reached, waiting %.1fs", wait)
                return max(base, wait)
        return base

    def _calculate_delay(self, now: float) -> float:
        if self.last_request_time is None:
            return random.uniform(
                self.min_delay * self.FIRST_REQUEST_DELAY_MULTIPLIER, self.min_delay,
            )
        since_last = now - self.last_request_time
        recent = self._count_recent(now, self.BURST_DETECTION_WINDOW_SECONDS)

        if recent >= self.burst_size:
            base = self.max_delay
            jitter = random.uniform(0, self.max_delay * self.BURST_JITTER_MULTIPLIER)
            logger.debug("Burst detected, longer delay")
        else:
            base = random.uniform(self.min_delay, self.max_delay)
            jitter = random.uniform(self.NORMAL_JITTER_MIN, self.NORMAL_JITTER_MAX)

        needed = max(0, self.min_delay - since_last)
        return max(needed, base + jitter)

    def reset(self) -> None:
        with self.lock:
            self.request_times.clear()
            self.last_request_time = None

    def get_stats(self) -> Dict[str, Optional[float]]:
        with self.lock:
            now = time.time()
            return {
                "requests_in_last_minute": self._count_recent(now, self.WINDOW_SIZE_SECONDS),
                "max_requests_per_minute": self.requests_per_minute,
                "last_request_ago": (
                    now - self.last_request_time if self.last_request_time else None
                ),
                "min_delay": self.min_delay,
                "max_delay": self.max_delay,
            }
