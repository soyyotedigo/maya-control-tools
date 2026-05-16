"""Search helpers for filtering shape labels in the UI."""


def search_shapes(items: list, query: str) -> list:
    """Return items whose string representation contains *query*.

    Case-insensitive substring match.  Returns all items unchanged when
    *query* is empty.
    """
    if not query:
        return items
    q = query.lower()
    return [x for x in items if q in str(x).lower()]
