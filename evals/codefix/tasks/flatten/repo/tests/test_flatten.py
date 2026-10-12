from flatten import flatten


def test_nested_keys_are_joined_with_dots():
    assert flatten({"a": {"b": 1}, "c": 2}) == {"a.b": 1, "c": 2}


def test_calls_are_independent():
    flatten({"a": {"b": 1}})
    assert flatten({"c": 2}) == {"c": 2}
