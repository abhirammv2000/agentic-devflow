# Flattening twice returns keys from the first call

flatten({"a": {"b": 1}}) returns {"a.b": 1}. Calling flatten({"c": 2}) afterwards returns {"a.b": 1, "c": 2}, but it should return {"c": 2}.

Each call should return a new dict that only holds keys from its own input. Nested dicts are flattened with dots joining the keys, and values that are not dicts are kept as they are.
