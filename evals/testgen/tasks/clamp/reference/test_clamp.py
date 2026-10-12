import pytest

from clamp import clamp


def test_value_inside_the_range_is_unchanged():
    assert clamp(5, 0, 10) == 5


def test_below_the_range_gives_low():
    assert clamp(-3, 0, 10) == 0


def test_above_the_range_gives_high():
    assert clamp(42, 0, 10) == 10


def test_equal_bounds_are_allowed():
    assert clamp(5, 5, 5) == 5
    assert clamp(9, 5, 5) == 5


def test_reversed_bounds_are_an_error():
    with pytest.raises(ValueError):
        clamp(1, 10, 0)


def test_works_with_floats_and_negatives():
    assert clamp(-0.5, -1.0, -0.25) == -0.5
    assert clamp(0.0, -1.0, -0.25) == -0.25
