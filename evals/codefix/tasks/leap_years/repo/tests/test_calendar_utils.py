from calendar_utils import days_in_month


def test_ordinary_leap_year():
    assert days_in_month(2024, 2) == 29


def test_century_is_not_a_leap_year():
    assert days_in_month(1900, 2) == 28
