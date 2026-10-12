import pytest

from billing import split_bill


def test_even_split():
    assert split_bill(100, 4) == [25, 25, 25, 25]


def test_extra_cents_go_to_the_first_people():
    assert split_bill(100, 3) == [34, 33, 33]


def test_fewer_cents_than_people():
    assert split_bill(1, 3) == [1, 0, 0]


def test_zero_total():
    assert split_bill(0, 4) == [0, 0, 0, 0]


def test_one_person_pays_everything():
    assert split_bill(999, 1) == [999]


def test_shares_always_add_up_and_differ_by_at_most_one():
    for total in range(0, 60):
        for people in range(1, 9):
            shares = split_bill(total, people)
            assert len(shares) == people
            assert sum(shares) == total
            assert max(shares) - min(shares) <= 1


def test_no_people_is_an_error():
    with pytest.raises(ValueError):
        split_bill(100, 0)


def test_uneven_split_adds_up():
    assert sum(split_bill(100, 3)) == 100
