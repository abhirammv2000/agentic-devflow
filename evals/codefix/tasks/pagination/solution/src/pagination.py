def paginate(items, page, per_page):
    """Return the items on a page. Pages are numbered from 1."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be at least 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]
