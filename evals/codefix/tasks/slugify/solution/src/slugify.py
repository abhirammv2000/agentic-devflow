import re


def slugify(text):
    """Turn a title into a URL slug: lowercase words joined by hyphens."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
