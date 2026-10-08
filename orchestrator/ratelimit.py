"""A sliding-window limit on how many runs may start per minute.

Each run can spend many model calls, so a loop in a workflow (or a webhook delivered over and over) is
a cost problem before it is anything else. This is a backstop for that. It is per process and in
memory, which is right for one orchestrator instance and not for several.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class RateLimiter:
    def __init__(self, per_minute: Callable[[], int], clock: Callable[[], float] = time.monotonic) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._hits: deque[float] = deque()

    def check(self) -> int | None:
        """Count this request. Returns None if it is allowed, else the seconds to wait."""
        limit, now = self._per_minute(), self._clock()
        while self._hits and now - self._hits[0] >= 60:
            self._hits.popleft()
        if limit > 0 and len(self._hits) >= limit:
            return int(60 - (now - self._hits[0])) + 1
        self._hits.append(now)
        return None
