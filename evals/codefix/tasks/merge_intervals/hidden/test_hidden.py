from intervals import merge_intervals


def test_overlapping_intervals_in_order():
    assert merge_intervals([[1, 3], [2, 6]]) == [[1, 6]]


def test_unsorted_and_touching():
    assert merge_intervals([[3, 5], [1, 2], [2, 3]]) == [[1, 5]]


def test_disjoint_intervals_are_kept_apart():
    assert merge_intervals([[1, 2], [4, 5]]) == [[1, 2], [4, 5]]


def test_nested_interval():
    assert merge_intervals([[1, 10], [2, 3]]) == [[1, 10]]


def test_empty_input():
    assert merge_intervals([]) == []


def test_input_is_not_changed():
    data = [[5, 6], [1, 5]]
    merge_intervals(data)
    assert data == [[5, 6], [1, 5]]


def test_result_does_not_share_lists_with_the_input():
    data = [[1, 2]]
    result = merge_intervals(data)
    result[0][1] = 99
    assert data == [[1, 2]]


def test_many_intervals_out_of_order():
    assert merge_intervals([[8, 10], [1, 3], [15, 18], [2, 6]]) == [[1, 6], [8, 10], [15, 18]]
