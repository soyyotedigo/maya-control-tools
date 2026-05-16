"""Tests for the database manager — no Maya required."""

import json
import os
import sqlite3
import tempfile
import pytest

from app.database import manager


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Redirect the database to a temporary file for each test."""
    db_path = str(tmp_path / "test_controlme.db")
    monkeypatch.setattr("app.paths.get_db_path", lambda: db_path)
    manager.initialize()
    return db_path


def test_initialize_creates_tables():
    with manager.get_connection() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "shapes" in tables
    assert "groups" in tables
    assert "shape_groups" in tables
    assert "schema_version" in tables
    assert "deleted_builtins" in tables


def test_shapes_table_has_new_columns():
    with manager.get_connection() as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(shapes)").fetchall()}
    assert "cv_count" in columns
    assert "degree" in columns
    assert "knots" in columns
    assert "position" in columns
    assert "color" in columns
    assert "sort_order" in columns


def test_save_custom_shape_minimal():
    cv_positions = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
    shapes_data = [{"cv_positions": cv_positions, "degree": 1, "knots": None}]
    row_id = manager.save_custom_shape("test_tri", "Test Triangle", shapes_data)
    assert row_id > 0

    shape = manager.get_shape("test_tri")
    assert shape is not None
    assert shape["label"] == "Test Triangle"
    assert shape["cv_count"] == 3
    assert shape["degree"] == 1
    assert shape["knots"] is None
    assert shape["position"] is None
    assert shape["is_builtin"] == 0
    assert json.loads(shape["cv_data"]) == [list(p) for p in cv_positions]


def test_save_custom_shape_full():
    cv_positions = [(0, 0, 0), (1, 0, 0), (2, 1, 0), (3, 0, 0)]
    knots = [0, 1, 2, 3, 4, 5]
    position = (5.0, 10.0, -3.0)
    shapes_data = [{"cv_positions": cv_positions, "degree": 3, "knots": knots}]

    row_id = manager.save_custom_shape(
        name="test_curve",
        label="Test Curve",
        shapes_data=shapes_data,
        position=position,
    )
    assert row_id > 0

    shape = manager.get_shape("test_curve")
    assert shape["cv_count"] == 4
    assert shape["degree"] == 3
    assert json.loads(shape["knots"]) == knots
    assert json.loads(shape["position"]) == [5.0, 10.0, -3.0]


def test_seed_builtins_populates_cv_data():
    manager.seed_builtins()
    shape = manager.get_shape("square")
    assert shape is not None
    assert shape["is_builtin"] == 1
    assert shape["cv_count"] == 5
    assert shape["degree"] == 1
    cv_data = json.loads(shape["cv_data"])
    assert len(cv_data) == 5


def test_seed_builtins_circle_defaults():
    manager.seed_builtins()
    shape = manager.get_shape("circle")
    assert shape is not None
    assert shape["cv_count"] == 8
    assert shape["degree"] == 3


def test_delete_shape():
    manager.save_custom_shape(
        "to_delete",
        "Delete Me",
        [{"cv_positions": [(0, 0, 0)], "degree": 1, "knots": None}],
    )
    manager.delete_shape("to_delete")
    assert manager.get_shape("to_delete") is None


def test_save_custom_shape_multishape_uses_v2_payload():
    shapes_data = [
        {"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None, "form": 0},
        {
            "cv_positions": [(0, 0, 0), (0, 1, 0)],
            "degree": 1,
            "knots": [0, 1],
            "form": 1,
        },
    ]

    manager.save_custom_shape("combo", "Combo", shapes_data)

    shape = manager.get_shape("combo")
    payload = json.loads(shape["cv_data"])
    assert payload["v"] == 2
    assert len(payload["shapes"]) == 2
    assert shape["cv_count"] == 4


def test_duplicate_shape_creates_numbered_copy_after_source():
    shape = [{"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None}]
    manager.save_custom_shape("circle", "Circle", shape)
    manager.save_custom_shape("arrow", "Arrow", shape)
    with manager.get_connection() as conn:
        conn.execute("UPDATE shapes SET sort_order = 1 WHERE name = 'circle'")
        conn.execute("UPDATE shapes SET sort_order = 2 WHERE name = 'arrow'")

    new_name = manager.duplicate_shape("circle")

    with manager.get_connection() as conn:
        rows = conn.execute(
            "SELECT name, label, sort_order FROM shapes ORDER BY sort_order"
        ).fetchall()
    assert new_name == "circle1"
    assert [(row["name"], row["sort_order"]) for row in rows] == [
        ("circle", 1),
        ("circle1", 2),
        ("arrow", 3),
    ]
    assert rows[1]["label"] == "Circle 1"


def test_rename_shape_appends_suffix_on_collision():
    shape = [{"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None}]
    manager.save_custom_shape("circle", "Circle", shape)
    manager.save_custom_shape("arrow", "Arrow", shape)

    new_name = manager.rename_shape("circle", "Arrow")

    assert new_name == "arrow1"
    renamed = manager.get_shape("arrow1")
    assert renamed is not None
    assert renamed["label"] == "Arrow"
    assert manager.get_shape("circle") is None


def test_delete_builtin_tracks_deleted_builtins():
    manager.seed_builtins()

    manager.delete_shape("circle")

    with manager.get_connection() as conn:
        deleted = conn.execute("SELECT name FROM deleted_builtins").fetchall()
    assert {row[0] for row in deleted} == {"circle"}
    assert manager.get_shape("circle") is None


def test_groups_can_be_created_and_assigned():
    manager.save_custom_shape(
        "shape_a",
        "Shape A",
        [{"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None}],
    )

    manager.create_group("rig")
    manager.assign_to_group("shape_a", "rig")

    groups = manager.get_groups()
    with manager.get_connection() as conn:
        rows = conn.execute("SELECT shape_id, group_id FROM shape_groups").fetchall()
    assert [group["name"] for group in groups] == ["rig"]
    assert len(rows) == 1


def test_initialize_twice_preserves_latest_schema_version(tmp_path, monkeypatch):
    """Calling initialize() repeatedly should preserve the latest schema."""
    manager.initialize()
    manager.initialize()
    with manager.get_connection() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(shapes)").fetchall()}
    assert version == manager._CURRENT_VERSION
    assert {"color", "sort_order", "cv_count", "degree", "knots", "position"} <= columns
