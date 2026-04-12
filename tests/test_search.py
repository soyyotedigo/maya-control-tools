"""Tests for search strategies — no Maya required."""
import pytest
from app.models.search import (
    ContainsStrategy,
    EndsWithStrategy,
    NameSearcher,
    StartsWithStrategy,
)

NAMES = ["Circle", "Square", "Arrow", "Cross", "Diamond", "Double Arrow"]


def test_contains():
    result = ContainsStrategy().search(NAMES, "ar")
    assert "Square" in result
    assert "Arrow" in result
    assert "Double Arrow" in result
    assert "Circle" not in result


def test_starts_with():
    result = StartsWithStrategy().search(NAMES, "ar")
    assert result == ["Arrow"]


def test_ends_with():
    result = EndsWithStrategy().search(NAMES, "ow")
    assert "Arrow" in result
    assert "Double Arrow" in result


def test_empty_term_returns_all():
    searcher = NameSearcher()
    assert searcher.search(NAMES, "") == NAMES


def test_case_insensitive():
    result = ContainsStrategy().search(NAMES, "CIRCLE")
    assert result == ["Circle"]


def test_no_match_returns_empty():
    result = ContainsStrategy().search(NAMES, "xyz")
    assert result == []


def test_searcher_swaps_strategy():
    searcher = NameSearcher(StartsWithStrategy())
    assert searcher.search(NAMES, "ar") == ["Arrow"]
    searcher.set_strategy(ContainsStrategy())
    result = searcher.search(NAMES, "ar")
    assert len(result) > 1
