from intervals import merge_intervals


def test_overlapping_intervals_in_order():
    assert merge_intervals([[1, 3], [2, 6]]) == [[1, 6]]


def test_unsorted_and_touching():
    assert merge_intervals([[3, 5], [1, 2], [2, 3]]) == [[1, 5]]
