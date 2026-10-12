import pytest

from calendar_utils import days_in_month, is_leap_year


def test_ordinary_leap_year():
    assert days_in_month(2024, 2) == 29


def test_ordinary_common_year():
    assert days_in_month(2023, 2) == 28


def test_century_is_not_a_leap_year():
    assert days_in_month(1900, 2) == 28
    assert days_in_month(2100, 2) == 28


def test_fourth_century_is_a_leap_year():
    assert days_in_month(2000, 2) == 29
    assert days_in_month(2400, 2) == 29


def test_is_leap_year_rule():
    assert [is_leap_year(y) for y in (1896, 1900, 2000, 2023, 2024)] == [True, False, True, False, True]


def test_thirty_and_thirty_one_day_months():
    assert [days_in_month(2023, m) for m in range(1, 13) if m != 2] == [31, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def test_month_out_of_range_is_an_error():
    for bad in (0, 13, -1):
        with pytest.raises(ValueError):
            days_in_month(2023, bad)
