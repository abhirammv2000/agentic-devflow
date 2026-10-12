class RateLimiter:
    """Allow at most `limit` calls in any window of `window` seconds."""

    def __init__(self, limit, window, clock):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.calls = []

    def allow(self):
        now = self.clock()
        self.calls = [t for t in self.calls if now - t < self.window]
        if len(self.calls) > self.limit:
            return False
        self.calls.append(now)
        return True
