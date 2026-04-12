"""UI tests for OutlinerWidget and ImageView."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compat import QtCore, QtWidgets
from app.core.shape_data import decode_color
from app.views.groups_view import OutlinerWidget
from app.views.images_view import IMAGE_SIZES, ImageView


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture
def outliner(qapp):
    widget = OutlinerWidget()
    yield widget
    widget.close()


@pytest.fixture
def image_view(qapp):
    widget = ImageView()
    yield widget
    widget.close()


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
            "cv_data": json.dumps({"v": 1, "cv": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "form": 0}),
            "degree": 1,
            "color": None,
        },
    ]


class TestOutlinerWidget:
    def test_populate_and_selected_keys(self, outliner):
        outliner.populate({"circle": "Circle", "arrow": "Arrow"})

        outliner.list_widget.setCurrentRow(1)
        outliner.list_widget.item(0).setSelected(True)
        outliner.list_widget.item(1).setSelected(True)

        assert outliner.selected_key() == "arrow"
        assert set(outliner.selected_keys()) == {"circle", "arrow"}

    def test_search_filters_visible_items(self, outliner):
        outliner.populate({"circle": "Circle", "arrow": "Arrow", "cross": "Cross"})

        outliner.search_line.setText("ar")

        assert outliner.list_widget.count() == 1
        assert outliner.list_widget.item(0).text() == "Arrow"

    def test_add_shape_item_respects_active_filter(self, outliner):
        outliner.populate({"circle": "Circle"})
        outliner.search_line.setText("arr")

        outliner.add_shape_item("arrow", "Arrow")
        outliner.add_shape_item("cross", "Cross")

        assert [outliner.list_widget.item(i).text() for i in range(outliner.list_widget.count())] == ["Arrow"]
        assert ("arrow", "Arrow") in outliner._all_items
        assert ("cross", "Cross") in outliner._all_items

    def test_item_rename_emits_and_blank_name_reverts(self, outliner):
        outliner.populate({"circle": "Circle"})
        item = outliner.list_widget.item(0)
        captured = []
        outliner.shape_renamed.connect(lambda old_key, new_label: captured.append((old_key, new_label)))

        outliner.list_widget.blockSignals(True)
        item.setText("Circle Renamed")
        outliner.list_widget.blockSignals(False)
        outliner._on_item_renamed(item)
        outliner.list_widget.blockSignals(True)
        item.setText("   ")
        outliner.list_widget.blockSignals(False)
        outliner._on_item_renamed(item)

        assert captured == [("circle", "Circle Renamed")]
        assert item.text() == "Circle"


class TestImageView:
    def test_populate_and_selected_keys(self, image_view):
        image_view.populate(_sample_shapes())

        image_view.list_widget.setCurrentRow(0)
        image_view.list_widget.item(0).setSelected(True)
        image_view.list_widget.item(1).setSelected(True)

        assert image_view.selected_key() == "circle"
        assert set(image_view.selected_keys()) == {"circle", "arrow"}

    def test_rename_shape_item_updates_shape_and_item(self, image_view):
        image_view.populate(_sample_shapes())

        image_view.rename_shape_item("circle", "circle_2", "Circle 2")
        item = image_view.list_widget.item(0)

        assert image_view._shapes[0]["name"] == "circle_2"
        assert image_view._shapes[0]["label"] == "Circle 2"
        assert item.data(QtCore.Qt.UserRole) == "circle_2"
        assert item.text() == "Circle 2"
        assert item.toolTip() == "Circle 2"

    def test_update_shape_color_stores_encoded_color(self, image_view):
        image_view.populate(_sample_shapes())

        image_view.update_shape_color("arrow", (0.25, 0.5, 0.75))

        assert decode_color(image_view._shapes[1]["color"]) == (0.25, 0.5, 0.75)

    def test_size_change_updates_icon_and_grid_size(self, image_view):
        image_view.populate(_sample_shapes())

        image_view._on_size_changed(3)

        assert image_view.list_widget.iconSize() == QtCore.QSize(IMAGE_SIZES[3], IMAGE_SIZES[3])
        assert image_view.list_widget.gridSize() == QtCore.QSize(IMAGE_SIZES[3] + 12, IMAGE_SIZES[3] + 28)

    def test_current_color_pick_shape_uses_default_and_decoded_color(self, image_view):
        shapes = _sample_shapes()
        shapes[1]["color"] = "[0.1, 0.2, 0.3]"
        image_view.populate(shapes)

        image_view._context_item = image_view.list_widget.item(0)
        default_name, default_color = image_view._current_color_pick_shape()
        image_view._context_item = image_view.list_widget.item(1)
        colored_name, colored_color = image_view._current_color_pick_shape()

        assert default_name == "circle"
        assert default_color == (1.0, 1.0, 0.0)
        assert colored_name == "arrow"
        assert colored_color == (0.1, 0.2, 0.3)

    def test_item_rename_emits_only_for_real_change_and_blank_reverts(self, image_view):
        image_view.populate(_sample_shapes())
        item = image_view.list_widget.item(0)
        captured = []
        image_view.shape_renamed.connect(lambda old_key, new_label: captured.append((old_key, new_label)))

        image_view.list_widget.blockSignals(True)
        item.setText("Circle")
        image_view.list_widget.blockSignals(False)
        image_view._on_item_renamed(item)
        image_view.list_widget.blockSignals(True)
        item.setText("Circle Prime")
        image_view.list_widget.blockSignals(False)
        image_view._on_item_renamed(item)
        image_view.list_widget.blockSignals(True)
        item.setText("")
        image_view.list_widget.blockSignals(False)
        image_view._on_item_renamed(item)

        assert captured == [("circle", "Circle Prime")]
        assert item.text() == "Circle"