def compare_versions(a, b):
    """Return -1, 0 or 1 as version a is older than, equal to or newer than b."""
    left = [int(part) for part in a.split(".")]
    right = [int(part) for part in b.split(".")]
    size = max(len(left), len(right))
    left += [0] * (size - len(left))
    right += [0] * (size - len(right))
    if left < right:
        return -1
    if left > right:
        return 1
    return 0
