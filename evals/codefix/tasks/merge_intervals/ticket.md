# Intervals are only merged when they arrive in order

merge_intervals([[3, 5], [1, 2], [2, 3]]) should return [[1, 5]].

The input can be in any order, and intervals that touch (one ends exactly where the next starts) should be merged. Return a new list of [start, end] lists and do not change the input.
