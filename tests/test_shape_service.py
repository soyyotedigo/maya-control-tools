from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.core.shape_service import ShapeService


def test_list_shapes_filters_by_label(monkeypatch):
    shapes = [
        {"name": "circle", "label": "Circle"},
        {"name": "arrow", "label": "Arrow"},
        {"name": "cross", "label": "Cross"},
    ]
    monkeypatch.setattr("app.core.shape_service.db.get_all_shapes", lambda: shapes)

    svc = ShapeService()

    assert [shape["name"] for shape in svc.list_shapes("arr")] == ["arrow"]
    assert svc.list_shapes("") == shapes


def test_save_shape_updates_color_when_present(monkeypatch):
    save_mock = MagicMock()
    color_mock = MagicMock()
    monkeypatch.setattr("app.core.shape_service.db.save_custom_shape", save_mock)
    monkeypatch.setattr("app.core.shape_service.db.update_shape_color", color_mock)

    svc = ShapeService()
    svc.save_shape(
        name="custom",
        label="Custom",
        shapes_data=[
            {"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None}
        ],
        color=(0.2, 0.4, 0.6),
    )

    save_mock.assert_called_once_with(
        name="custom",
        label="Custom",
        shapes_data=[
            {"cv_positions": [(0, 0, 0), (1, 0, 0)], "degree": 1, "knots": None}
        ],
    )
    color_mock.assert_called_once_with("custom", (0.2, 0.4, 0.6))


def test_duplicate_rename_and_delete_proxy_db_calls(monkeypatch):
    duplicate_mock = MagicMock(return_value="circle1")
    rename_mock = MagicMock(return_value="circle_prime")
    delete_mock = MagicMock()
    monkeypatch.setattr("app.core.shape_service.db.duplicate_shape", duplicate_mock)
    monkeypatch.setattr("app.core.shape_service.db.rename_shape", rename_mock)
    monkeypatch.setattr("app.core.shape_service.db.delete_shape", delete_mock)

    svc = ShapeService()

    assert svc.duplicate_shape("circle") == "circle1"
    assert svc.rename_shape("circle", "Circle Prime") == "circle_prime"
    svc.delete_shape("circle_prime")

    duplicate_mock.assert_called_once_with("circle")
    rename_mock.assert_called_once_with("circle", "Circle Prime")
    delete_mock.assert_called_once_with("circle_prime")


def test_export_shapes_writes_existing_rows_only(tmp_path, monkeypatch):
    shapes = {
        "circle": {"name": "circle", "label": "Circle"},
        "arrow": {"name": "arrow", "label": "Arrow"},
    }
    monkeypatch.setattr(
        "app.core.shape_service.db.get_shape", lambda name: shapes.get(name)
    )

    path = tmp_path / "shapes.json"
    svc = ShapeService()
    svc.export_shapes(str(path), ["circle", "missing", "arrow"])

    exported = json.loads(path.read_text())
    assert [shape["name"] for shape in exported] == ["circle", "arrow"]


def test_import_shapes_saves_valid_rows_and_skips_invalid(tmp_path, monkeypatch):
    payload = [
        {
            "name": "circle",
            "label": "Circle",
            "cv_data": json.dumps([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
            "degree": 1,
            "knots": None,
            "color": json.dumps([0.1, 0.2, 0.3]),
        },
        {
            "label": "Broken",
            "cv_data": "not-json",
        },
    ]
    path = tmp_path / "import.json"
    path.write_text(json.dumps(payload))

    save_mock = MagicMock()
    color_mock = MagicMock()
    monkeypatch.setattr("app.core.shape_service.db.save_custom_shape", save_mock)
    monkeypatch.setattr("app.core.shape_service.db.update_shape_color", color_mock)

    svc = ShapeService()
    imported = svc.import_shapes(str(path))

    assert imported == ["circle"]
    save_mock.assert_called_once_with(
        name="circle",
        label="Circle",
        shapes_data=[
            {
                "cv_positions": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "degree": 1,
                "knots": None,
            }
        ],
    )
    color_mock.assert_called_once_with("circle", [0.1, 0.2, 0.3])
