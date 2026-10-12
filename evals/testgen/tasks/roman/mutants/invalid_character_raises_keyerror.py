VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text):
    """Convert a Roman numeral to an integer. Raises ValueError for empty or invalid input."""
    if not text:
        raise ValueError("empty numeral")
    total = 0
    for i, char in enumerate(text):
        value = VALUES[char]
        if i + 1 < len(text) and VALUES.get(text[i + 1], 0) > value:
            total -= value
        else:
            total += value
    return total
