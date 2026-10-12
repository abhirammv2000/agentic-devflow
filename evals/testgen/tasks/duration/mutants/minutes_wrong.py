import re

UNITS = {"h": 3600, "m": 6, "s": 1}


def parse_duration(text):
    """Parse a duration such as "1h30m", "45s" or "2h" into seconds."""
    if not re.fullmatch(r"(\d+[hms])+", text):
        raise ValueError("bad duration: " + repr(text))
    return sum(int(n) * UNITS[u] for n, u in re.findall(r"(\d+)([hms])", text))
