from ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_calls_under_the_limit_are_allowed():
    clock = FakeClock()
    limiter = RateLimiter(2, 10, clock)
    assert limiter.allow()
    assert limiter.allow()


def test_third_call_in_the_window_is_refused():
    clock = FakeClock()
    limiter = RateLimiter(2, 10, clock)
    assert [limiter.allow() for _ in range(3)] == [True, True, False]
