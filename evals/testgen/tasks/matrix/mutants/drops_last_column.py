def transpose(matrix):
    """Transpose a rectangular matrix given as a list of rows. An empty matrix gives []."""
    if not matrix:
        return []
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError("rows have different lengths")
    return [[row[c] for row in matrix] for c in range(width - 1)]
