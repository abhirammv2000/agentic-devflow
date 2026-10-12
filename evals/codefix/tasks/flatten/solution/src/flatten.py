def flatten(data, prefix="", out=None):
    """Flatten nested dicts into one dict with dotted keys."""
    if out is None:
        out = {}
    for key, value in data.items():
        name = prefix + key
        if isinstance(value, dict):
            flatten(value, name + ".", out)
        else:
            out[name] = value
    return out
