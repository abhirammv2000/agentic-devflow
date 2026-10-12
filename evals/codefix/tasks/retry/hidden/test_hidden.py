import pytest

from retry import retry


def make_flaky(fail_times):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) <= fail_times:
            raise RuntimeError("failure {}".format(len(calls)))
        return "ok"

    flaky.calls = calls
    return flaky


def test_returns_the_first_success():
    assert retry(lambda: 5, 3) == 5


def test_retries_until_it_works():
    flaky = make_flaky(2)
    assert retry(flaky, 3) == "ok"
    assert len(flaky.calls) == 3


def test_stops_after_the_first_success():
    flaky = make_flaky(0)
    retry(flaky, 5)
    assert len(flaky.calls) == 1


def test_raises_the_last_error_when_every_attempt_fails():
    flaky = make_flaky(10)
    with pytest.raises(RuntimeError, match="failure 3"):
        retry(flaky, 3)
    assert len(flaky.calls) == 3


def test_one_attempt_means_one_call():
    flaky = make_flaky(10)
    with pytest.raises(RuntimeError, match="failure 1"):
        retry(flaky, 1)
    assert len(flaky.calls) == 1


def test_attempts_below_one_is_an_error():
    with pytest.raises(ValueError):
        retry(lambda: 1, 0)


def test_a_falsy_result_still_counts_as_success():
    assert retry(lambda: 0, 2) == 0
