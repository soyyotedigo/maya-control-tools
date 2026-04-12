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


# ------------------------------------------------------------------
# Legacy strategy classes kept for backward compatibility
# ------------------------------------------------------------------

class SearchStrategy:
    def search(self, names: list, term: str) -> list:
        raise NotImplementedError


class StartsWithStrategy(SearchStrategy):
    def search(self, names: list, term: str) -> list:
        return [n for n in names if n.lower().startswith(term.lower())]


class ContainsStrategy(SearchStrategy):
    def search(self, names: list, term: str) -> list:
        return [n for n in names if term.lower() in n.lower()]


class EndsWithStrategy(SearchStrategy):
    def search(self, names: list, term: str) -> list:
        return [n for n in names if n.lower().endswith(term.lower())]


class NameSearcher:
    def __init__(self, strategy: SearchStrategy = None):
        self.strategy = strategy or ContainsStrategy()

    def set_strategy(self, strategy: SearchStrategy) -> None:
        self.strategy = strategy

    def search(self, names: list, term: str) -> list:
        if not term:
            return names
        return self.strategy.search(names, term)
