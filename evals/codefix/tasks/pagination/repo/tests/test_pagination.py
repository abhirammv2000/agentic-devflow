from pagination import paginate


def test_second_page():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]


def test_first_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]
