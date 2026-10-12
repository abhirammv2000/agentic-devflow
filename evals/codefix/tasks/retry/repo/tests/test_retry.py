from retry import retry


def test_returns_the_first_success():
    assert retry(lambda: 5, 3) == 5


def test_retries_until_it_works():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("not yet")
        return "ok"

    assert retry(flaky, 3) == "ok"
