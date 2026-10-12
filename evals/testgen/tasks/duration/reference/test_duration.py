import pytest

from duration import parse_duration


def test_each_unit_alone():
    assert parse_duration("2h") == 7200
    assert parse_duration("5m") == 300
    assert parse_duration("45s") == 45


def test_units_add_up():
    assert parse_duration("1h30m") == 5400
    assert parse_duration("1h1m1s") == 3661


def test_multi_digit_numbers():
    assert parse_duration("120m") == 7200
    assert parse_duration("100s") == 100


def test_the_same_unit_can_repeat():
    assert parse_duration("10s20s") == 30


def test_empty_string_is_an_error():
    with pytest.raises(ValueError):
        parse_duration("")


def test_unknown_unit_or_junk_is_an_error():
    for bad in ("5x", "1hxyz", "h", "1 h", "abc", "1h 30m", "-5s"):
        with pytest.raises(ValueError):
            parse_duration(bad)
