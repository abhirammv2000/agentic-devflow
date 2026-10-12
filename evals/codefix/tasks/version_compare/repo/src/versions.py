def compare_versions(a, b):
    """Return -1, 0 or 1 as version a is older than, equal to or newer than b."""
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
