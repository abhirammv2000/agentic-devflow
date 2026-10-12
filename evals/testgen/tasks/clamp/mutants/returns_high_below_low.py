def clamp(value, low, high):
    """Limit value to the range from low to high. low must not be greater than high."""
    if low > high:
        raise ValueError("low must not be greater than high")
    if value < low:
        return high
    if value > high:
        return high
    return value
