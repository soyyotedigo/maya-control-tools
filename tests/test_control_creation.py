"""Tests for control_creation.py (no Maya required)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# Inject Maya stubs directly so this test file can run without PySide.
sys.modules.setdefault("maya", MagicMock())
sys.modules.setdefault("maya.cmds", MagicMock())
sys.modules.setdefault("maya.api", MagicMock())
sys.modules.setdefault("maya.api.OpenMaya", MagicMock())


def _cmds(**overrides) -> MagicMock:
    m = MagicMock()
    m.ls.return_value = []
    m.listRelatives.return_value = []
    m.filterExpand.return_value = []
    m.polyListComponentConversion.return_value = []
    m.polyInfo.return_value = ["EDGE 0: 0 1"]
    m.select.return_value = None
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestUniqueShapeIdentity:
    def test_keeps_name_when_unique(self):
        from app.core.control_creation import unique_shape_identity

        key, label = unique_shape_identity("My Control", {"other"})

        assert key == "my_control"
        assert label == "My Control"

    def test_appends_suffix_when_exists(self):
        from app.core.control_creation import unique_shape_identity

        key, label = unique_shape_identity("My Control", {"my_control", "my_control1"})

        assert key == "my_control2"
        assert label == "My Control 2"


class TestResolveControlSelection:
    def test_prefers_curve_transforms(self):
        from app.core.control_creation import resolve_control_selection

        mock = _cmds()
        mock.ls.return_value = ["curve_ctrl"]
        mock.listRelatives.return_value = ["curveShape"]

        with patch("app.core.control_creation._get_cmds", return_value=mock):
            selection = resolve_control_selection()

        assert selection.kind == "curves"
        assert selection.curve_transforms == ["curve_ctrl"]
        assert selection.edges == []

    def test_resolves_edges_from_direct_edge_selection(self):
        from app.core.control_creation import resolve_control_selection

        mock = _cmds()

        def filter_expand_side_effect(*args, **kwargs):
            if kwargs.get("selectionMask") == 32:
                return ["mesh.e[0]"]
            return []

        mock.filterExpand.side_effect = filter_expand_side_effect

        with patch("app.core.control_creation._get_cmds", return_value=mock):
            selection = resolve_control_selection()

        assert selection.kind == "edges"
        assert selection.edges == ["mesh.e[0]"]

    def test_returns_invalid_when_nothing_supported_selected(self):
        from app.core.control_creation import resolve_control_selection

        mock = _cmds()

        with patch("app.core.control_creation._get_cmds", return_value=mock):
            selection = resolve_control_selection()

        assert selection.kind == "invalid"
        assert selection.error is not None


class TestCreateShapesFromSelection:
    def test_creates_from_curves(self):
        from app.core.control_creation import ControlSelection, create_shapes_from_selection

        selection = ControlSelection(
            kind="curves",
            curve_transforms=["curve_ctrl"],
            edges=[],
        )
        shapes = [{"cv_positions": [[0, 0, 0], [1, 0, 0]], "degree": 1, "knots": None}]

        with patch("app.core.operations.create_control_from_curves", return_value=(None, shapes)):
            result = create_shapes_from_selection(selection)

        assert result.ok is True
        assert result.shapes_data == shapes

    def test_create_from_edges_selects_new_control(self):
        from app.core.control_creation import ControlSelection, create_shapes_from_selection

        selection = ControlSelection(
            kind="edges",
            curve_transforms=[],
            edges=["mesh.e[0]"],
        )
        ctrl = MagicMock()
        ctrl.name = "ctrl_tmp"
        shapes = [{"cv_positions": [[0, 0, 0], [1, 0, 0]], "degree": 1, "knots": None}]
        mock = _cmds()

        with patch("app.core.control_creation._get_cmds", return_value=mock), \
             patch("app.core.operations.undo_chunk"), \
             patch("app.core.operations.create_control_from_edges", return_value=(ctrl, shapes)):
            result = create_shapes_from_selection(selection)

        assert result.ok is True
        assert result.created_control == "ctrl_tmp"
        mock.select.assert_called_once_with("ctrl_tmp")

    def test_create_from_edges_conversion_error(self):
        from app.core.control_creation import ControlSelection, create_shapes_from_selection

        selection = ControlSelection(
            kind="edges",
            curve_transforms=[],
            edges=["mesh.e[0]"],
        )

        with patch("app.core.operations.undo_chunk"), \
             patch("app.core.operations.create_control_from_edges", side_effect=RuntimeError("boom")):
            result = create_shapes_from_selection(selection)

        assert result.ok is False
        assert result.error == "boom"
