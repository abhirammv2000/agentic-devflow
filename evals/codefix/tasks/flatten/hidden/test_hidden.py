from flatten import flatten


def test_nested_keys_are_joined_with_dots():
    assert flatten({"a": {"b": 1}, "c": 2}) == {"a.b": 1, "c": 2}


def test_calls_are_independent():
    flatten({"a": {"b": 1}})
    assert flatten({"c": 2}) == {"c": 2}


def test_each_call_returns_a_new_dict():
    first = flatten({"a": 1})
    second = flatten({"a": 1})
    assert first == second
    assert first is not second


def test_deep_nesting():
    assert flatten({"a": {"b": {"c": {"d": 4}}}}) == {"a.b.c.d": 4}


def test_non_dict_values_are_kept_whole():
    assert flatten({"a": [1, 2], "b": {"c": (3, 4)}}) == {"a": [1, 2], "b.c": (3, 4)}


def test_the_input_is_not_changed():
    data = {"a": {"b": 1}}
    flatten(data)
    assert data == {"a": {"b": 1}}


def test_empty_input():
    assert flatten({}) == {}
    assert flatten({"a": 1}) == {"a": 1}
