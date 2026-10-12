def wrap(text, width):
    """Break text into lines of at most `width` characters, splitting only at spaces.

    A word longer than width gets a line to itself.
    """
    if width < 1:
        raise ValueError("width must be at least 1")
    lines = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
