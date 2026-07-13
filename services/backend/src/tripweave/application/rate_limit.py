from dataclasses import dataclass
from time import monotonic


@dataclass(slots=True)
class RateLimitBucket:
    count: int
    reset_at: float


class FixedWindowRateLimiter:
    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._buckets: dict[str, RateLimitBucket] = {}

    def allow(self, key: str) -> bool:
        now = monotonic()
        bucket = self._buckets.get(key)
        if bucket is None or bucket.reset_at <= now:
            self._buckets[key] = RateLimitBucket(count=1, reset_at=now + self._window_seconds)
            return True
        if bucket.count >= self._max_attempts:
            return False
        bucket.count += 1
        return True
