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


def test_window_expiry_allows_calls_again():
    clock = FakeClock()
    limiter = RateLimiter(2, 10, clock)
    limiter.allow()
    limiter.allow()
    clock.now = 10.0
    assert limiter.allow()


def test_just_inside_the_window_is_still_refused():
    clock = FakeClock()
    limiter = RateLimiter(1, 10, clock)
    assert limiter.allow()
    clock.now = 9.9
    assert not limiter.allow()


def test_refused_calls_do_not_count():
    clock = FakeClock()
    limiter = RateLimiter(1, 10, clock)
    assert limiter.allow()
    clock.now = 5.0
    assert not limiter.allow()
    clock.now = 10.0
    assert limiter.allow()


def test_limit_of_one_over_a_long_run():
    clock = FakeClock()
    limiter = RateLimiter(1, 3, clock)
    results = []
    for second in range(9):
        clock.now = float(second)
        results.append(limiter.allow())
    assert results == [True, False, False, True, False, False, True, False, False]
