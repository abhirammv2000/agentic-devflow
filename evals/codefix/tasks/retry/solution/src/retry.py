def retry(fn, attempts):
    """Call fn until it succeeds, up to `attempts` times."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as error:
            last = error
    raise last
