import pytest

from pagination import paginate

ITEMS = list(range(10))


def test_first_page():
    assert paginate(ITEMS, 1, 3) == [0, 1, 2]


def test_second_page():
    assert paginate(ITEMS, 2, 3) == [3, 4, 5]


def test_last_page_can_be_short():
    assert paginate(ITEMS, 4, 3) == [9]


def test_page_past_the_end_is_empty():
    assert paginate(ITEMS, 5, 3) == []


def test_page_zero_is_an_error():
    with pytest.raises(ValueError):
        paginate(ITEMS, 0, 3)


def test_negative_page_is_an_error():
    with pytest.raises(ValueError):
        paginate(ITEMS, -1, 3)


def test_per_page_below_one_is_an_error():
    with pytest.raises(ValueError):
        paginate(ITEMS, 1, 0)


def test_empty_list():
    assert paginate([], 1, 5) == []
