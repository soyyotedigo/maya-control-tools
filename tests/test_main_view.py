from __future__ import annotations

import json

import pytest

from app.core.shape_data import decode_color
from app.core.control_creation import ControlCreationResult, ControlSelection
from app.views import main_view
from app.views import maya_integration


def _sample_shapes() -> list[dict]:
    return [
        {
            "name": "circle",
            "label": "Circle",
            "cv_data": json.dumps([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
            "degree": 1,
            "color": None,
        },
        {
            "name": "arrow",
            "label": "Arrow",
            "cv_data": json.dumps(
                {"v": 1, "cv": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "form": 0}
            ),
            "degree": 1,
            "color": json.dumps([0.2, 0.4, 0.6]),
        },
    ]


class _FakeSettings:
    def __init__(self):
        self._values: dict[str, object] = {}

    def value(self, key: str):
        return self._values.get(key)

    def setValue(self, key: str, value) -> None:
        self._values[key] = value


class _FakeShapeService:
    def __init__(self, shapes: list[dict] | None = None):
        self.shapes = {
            shape["name"]: dict(shape) for shape in (shapes or _sample_shapes())
        }
        self.initialize_calls = 0
        self.seed_calls = 0
        self.save_calls: list[dict] = []
        self.color_calls: list[tuple[str, tuple | None]] = []
        self.delete_calls: list[str] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def seed_builtins(self) -> None:
        self.seed_calls += 1

    def list_shapes(self, search: str = "") -> list[dict]:
        shapes = [dict(shape) for shape in self.shapes.values()]
        if not search:
            return shapes
        q = search.lower()
        return [shape for shape in shapes if q in shape["label"].lower()]

    def get_shape(self, name: str) -> dict | None:
        shape = self.shapes.get(name)
        return dict(shape) if shape else None

    def get_shape_labels(self) -> dict[str, str]:
        return {name: shape["label"] for name, shape in self.shapes.items()}

    def save_shape(
        self, name: str, label: str, shapes_data: list[dict], color=None
    ) -> None:
        if len(shapes_data) == 1:
            cv_data = json.dumps(shapes_data[0]["cv_positions"])
        else:
            cv_data = json.dumps(
                {
                    "v": 2,
                    "shapes": [
                        {
                            "cv": shape["cv_positions"],
                            "degree": shape.get("degree", 1),
                            "knots": shape.get("knots"),
                            "form": shape.get("form", 0),
                        }
                        for shape in shapes_data
                    ],
                }
            )
        self.shapes[name] = {
            "name": name,
            "label": label,
            "cv_data": cv_data,
            "degree": shapes_data[0].get("degree", 1),
            "color": json.dumps(list(color)) if color is not None else None,
        }
        self.save_calls.append(
            {
                "name": name,
                "label": label,
                "shapes_data": shapes_data,
                "color": color,
            }
        )

    def update_color(self, name: str, rgb: tuple | None) -> None:
        self.color_calls.append((name, rgb))
        if name in self.shapes:
            self.shapes[name]["color"] = (
                json.dumps(list(rgb)) if rgb is not None else None
            )

    def duplicate_shape(self, name: str) -> str | None:
        shape = self.shapes.get(name)
        if not shape:
            return None
        counter = 1
        new_name = f"{name}{counter}"
        while new_name in self.shapes:
            counter += 1
            new_name = f"{name}{counter}"
        self.shapes[new_name] = dict(
            shape, name=new_name, label=f"{shape['label']} {counter}"
        )
        return new_name

    def rename_shape(self, old: str, new_label: str) -> str:
        new_name = new_label.lower().replace(" ", "_")
        shape = self.shapes.pop(old)
        shape["name"] = new_name
        shape["label"] = new_label
        self.shapes[new_name] = shape
        return new_name

    def delete_shape(self, name: str) -> None:
        self.delete_calls.append(name)
        self.shapes.pop(name, None)


@pytest.fixture
def controlme_factory(monkeypatch, qapp):
    # Earlier tests (e.g. test_control_creation) register fake maya modules
    # in sys.modules, which makes app.compat.is_maya() return True. Force it
    # back to False inside maya_integration so maya_main_window() short-circuits
    # to None instead of touching the mocked maya.OpenMayaUI.
    monkeypatch.setattr(maya_integration, "is_maya", lambda: False)

    created: list[main_view.ControlMe] = []

    def _make(
        service: _FakeShapeService | None = None,
        settings: _FakeSettings | None = None,
    ) -> tuple[main_view.ControlMe, _FakeShapeService, _FakeSettings]:
        fake_service = service or _FakeShapeService()
        fake_settings = settings or _FakeSettings()
        monkeypatch.setattr(
            main_view.QtCore, "QSettings", lambda *args, **kwargs: fake_settings
        )
        widget = main_view.ControlMe(service=fake_service)
        created.append(widget)
        return widget, fake_service, fake_settings

    yield _make

    for widget in created:
        widget.close()


def test_load_shapes_refreshes_panels_from_service(controlme_factory):
    widget, service, _settings = controlme_factory()

    assert service.initialize_calls == 1
    assert service.seed_calls == 1
    assert widget.outliner.list_widget.count() == 2
    assert widget.image_view.list_widget.count() == 2

    service.shapes["cross"] = {
        "name": "cross",
        "label": "Cross",
        "cv_data": json.dumps([[0, 0, 0], [0, 1, 0]]),
        "degree": 1,
        "color": None,
    }

    widget._load_shapes()

    assert widget.outliner.list_widget.count() == 3
    assert widget.image_view.list_widget.count() == 3
    assert widget._shape_labels["cross"] == "Cross"


def test_selected_keys_fall_back_to_outliner_when_image_selection_is_empty(
    controlme_factory,
):
    widget, _service, _settings = controlme_factory()

    widget.image_view.list_widget.clearSelection()
    widget.outliner.list_widget.blockSignals(True)
    widget.outliner.list_widget.setCurrentRow(1)
    widget.outliner.list_widget.item(1).setSelected(True)
    widget.outliner.list_widget.blockSignals(False)

    assert widget._selected_keys() == ["arrow"]


def test_sync_outliner_from_image_selection_updates_selection_and_color_swatch(
    controlme_factory,
):
    widget, _service, _settings = controlme_factory()

    widget.image_view.list_widget.setCurrentRow(1)
    widget.image_view.list_widget.item(0).setSelected(True)
    widget.image_view.list_widget.item(1).setSelected(True)

    widget._sync_outliner_from_image_selection()

    assert set(widget.outliner.selected_keys()) == {"circle", "arrow"}
    assert widget.outliner.selected_key() == "arrow"
    assert widget.color_swatch.color == (0.2, 0.4, 0.6)


def test_duplicate_shape_adds_new_item_to_both_panels(controlme_factory):
    widget, _service, _settings = controlme_factory()

    widget.image_view.list_widget.setCurrentRow(0)
    widget.image_view.list_widget.item(0).setSelected(True)

    widget._duplicate_shape()

    assert "circle1" in widget._shape_labels
    assert widget.outliner.list_widget.count() == 3
    assert widget.image_view.list_widget.count() == 3


def test_delete_shape_aborts_when_user_cancels(controlme_factory, monkeypatch):
    widget, service, _settings = controlme_factory()

    widget.image_view.list_widget.setCurrentRow(0)
    widget.image_view.list_widget.item(0).setSelected(True)
    monkeypatch.setattr(
        main_view.QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view.QtWidgets.QMessageBox.No,
    )

    widget._delete_shape()

    assert service.delete_calls == []
    assert widget.outliner.list_widget.count() == 2
    assert widget.image_view.list_widget.count() == 2


def test_delete_shape_removes_selected_items_when_confirmed(
    controlme_factory, monkeypatch
):
    widget, service, _settings = controlme_factory()

    widget.image_view.list_widget.setCurrentRow(0)
    widget.image_view.list_widget.item(0).setSelected(True)
    monkeypatch.setattr(
        main_view.QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view.QtWidgets.QMessageBox.Yes,
    )

    widget._delete_shape()

    assert service.delete_calls == ["circle"]
    assert "circle" not in widget._shape_labels
    assert widget.outliner.list_widget.count() == 1
    assert widget.image_view.list_widget.count() == 1


def test_set_color_and_reset_color_update_service_and_view(controlme_factory):
    widget, service, _settings = controlme_factory()

    widget.image_view.list_widget.setCurrentRow(1)
    widget.image_view.list_widget.item(1).setSelected(True)

    widget._set_color((0.1, 0.2, 0.3))
    assert service.color_calls[-1] == ("arrow", (0.1, 0.2, 0.3))
    assert decode_color(widget.image_view._shapes[1]["color"]) == (0.1, 0.2, 0.3)

    widget._reset_color()
    assert service.color_calls[-1] == ("arrow", None)
    assert widget.image_view._shapes[1]["color"] is None


def test_create_control_from_selection_warns_on_invalid_selection(
    controlme_factory, monkeypatch
):
    widget, _service, _settings = controlme_factory()

    captured = []
    monkeypatch.setattr(
        main_view,
        "resolve_control_selection",
        lambda: ControlSelection(
            kind="invalid", curve_transforms=[], edges=[], error="pick something"
        ),
    )
    monkeypatch.setattr(
        main_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: captured.append(args),
    )

    widget._create_control_from_selection()

    assert captured == [(widget, "No Valid Selection", "pick something")]


def test_create_control_from_selection_saves_shape_and_updates_ui(
    controlme_factory, monkeypatch
):
    widget, service, _settings = controlme_factory()

    monkeypatch.setattr(
        main_view,
        "resolve_control_selection",
        lambda: ControlSelection(
            kind="curves", curve_transforms=["curve_ctrl"], edges=[]
        ),
    )
    monkeypatch.setattr(
        main_view.QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("My Control", True),
    )
    monkeypatch.setattr(
        main_view,
        "create_shapes_from_selection",
        lambda selection: ControlCreationResult(
            ok=True,
            shapes_data=[
                {"cv_positions": [[0, 0, 0], [1, 0, 0]], "degree": 1, "knots": None}
            ],
        ),
    )

    widget._create_control_from_selection()

    assert service.save_calls[-1]["name"] == "my_control"
    assert service.save_calls[-1]["label"] == "My Control"
    assert "my_control" in widget._shape_labels
    assert widget.outliner.list_widget.count() == 3
    assert widget.image_view.list_widget.count() == 3


def test_save_and_restore_settings_round_trip(controlme_factory):
    settings = _FakeSettings()

    widget, _service, _settings = controlme_factory(settings=settings)
    widget.image_view.size_slider.setValue(3)
    widget.image_view.projection_combo.setCurrentText("Top")
    widget._save_settings()
    widget.close()

    restored, _service2, _settings2 = controlme_factory(settings=settings)

    assert restored.image_view.size_slider.value() == 3
    assert restored.image_view.projection_combo.currentText() == "Top"
