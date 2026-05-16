"""Tests for the search_shapes helper — no Maya required."""

from app.models.search import search_shapes

NAMES = ["Circle", "Square", "Arrow", "Cross", "Diamond", "Double Arrow"]


def test_contains_substring():
    result = search_shapes(NAMES, "ar")
    assert "Square" in result
    assert "Arrow" in result
    assert "Double Arrow" in result
    assert "Circle" not in result


def test_empty_query_returns_all():
    assert search_shapes(NAMES, "") == NAMES


def test_case_insensitive():
    assert search_shapes(NAMES, "CIRCLE") == ["Circle"]


def test_no_match_returns_empty():
    assert search_shapes(NAMES, "xyz") == []
