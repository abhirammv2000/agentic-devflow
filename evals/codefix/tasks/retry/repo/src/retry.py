def retry(fn, attempts):
    """Call fn until it succeeds, up to `attempts` times."""
    for _ in range(attempts - 1):
        try:
            return fn()
        except Exception:
            pass
