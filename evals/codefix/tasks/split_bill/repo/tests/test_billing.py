from billing import split_bill


def test_even_split():
    assert split_bill(100, 4) == [25, 25, 25, 25]


def test_uneven_split_adds_up():
    assert sum(split_bill(100, 3)) == 100
