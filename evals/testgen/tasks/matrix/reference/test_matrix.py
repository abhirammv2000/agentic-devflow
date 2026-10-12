import pytest

from matrix import transpose


def test_square_matrix():
    assert transpose([[1, 2], [3, 4]]) == [[1, 3], [2, 4]]


def test_wide_matrix():
    assert transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]


def test_tall_matrix():
    assert transpose([[1], [2], [3]]) == [[1, 2, 3]]


def test_single_row_and_single_cell():
    assert transpose([[7, 8, 9]]) == [[7], [8], [9]]
    assert transpose([[7]]) == [[7]]


def test_empty_matrix():
    assert transpose([]) == []


def test_rows_of_different_lengths_are_an_error():
    with pytest.raises(ValueError):
        transpose([[1, 2], [3]])
    with pytest.raises(ValueError):
        transpose([[1], [2, 3]])


def test_transposing_twice_gives_the_original():
    m = [[1, 2, 3], [4, 5, 6]]
    assert transpose(transpose(m)) == m
