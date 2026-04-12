"""Tests for operations.py — no Maya required.

Uses ``patch("app.core.operations.cmds")`` to mock the module-level
``cmds`` reference inside operations.py, so the tests run without a
live Maya session.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

# Inject the Maya mock before importing anything that references maya.cmds.
import app.compat
app.compat.ensure_maya_mock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmds(**overrides) -> MagicMock:
    """Build a MagicMock for maya.cmds with sensible per-test defaults."""
    m = MagicMock()
    m.polyInfo.return_value = ["EDGE 0: 0 1"]
    m.createNode.return_value = "ctrl_tmp"
    m.polyToCurve.return_value = ["curve1"]
    m.pointPosition.return_value = [0.0, 0.0, 0.0]
    m.listRelatives.return_value = ["shapeA"]
    m.ls.return_value = ["shapeA.cv[0]", "shapeA.cv[1]"]
    m.xform.return_value = [0.0, 0.0, 0.0]
    m.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    m.undoInfo.return_value = None
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# 1. undo_chunk
# ---------------------------------------------------------------------------

class TestUndoChunk:
    def test_opens_and_closes_when_in_maya(self):
        from app.core.operations import undo_chunk
        mock = _cmds()
        with patch("app.core.operations.cmds", mock), \
             patch("app.compat.is_maya", return_value=True), \
             patch("app.compat.MAYA_AVAILABLE", True):
            with undo_chunk("TestChunk"):
                pass
        mock.undoInfo.assert_any_call(openChunk=True, chunkName="TestChunk")
        mock.undoInfo.assert_any_call(closeChunk=True)

    def test_noop_outside_maya(self):
        from app.core.operations import undo_chunk
        mock = _cmds()
        with patch("app.core.operations.cmds", mock), \
             patch("app.compat.MAYA_AVAILABLE", False):
            with undo_chunk("TestChunk"):
                pass
        mock.undoInfo.assert_not_called()

    def test_closes_even_on_exception(self):
        from app.core.operations import undo_chunk
        mock = _cmds()
        with patch("app.core.operations.cmds", mock), \
             patch("app.compat.MAYA_AVAILABLE", True):
            with pytest.raises(RuntimeError):
                with undo_chunk("TestChunk"):
                    raise RuntimeError("boom")
        mock.undoInfo.assert_any_call(closeChunk=True)


# ---------------------------------------------------------------------------
# 2. group_connected_edges
# ---------------------------------------------------------------------------

class TestGroupConnectedEdges:
    def test_single_chain_returns_one_group(self):
        from app.core.operations import group_connected_edges
        edges = ["mesh.e[0]", "mesh.e[1]", "mesh.e[2]"]
        mock = _cmds()
        # v0-v1-v2-v3: one connected chain
        mock.polyInfo.return_value = [
            "EDGE 0: 0 1",
            "EDGE 1: 1 2",
            "EDGE 2: 2 3",
        ]
        with patch("app.core.operations.cmds", mock):
            groups = group_connected_edges(edges)
        assert len(groups) == 1
        assert set(groups[0]) == set(edges)

    def test_two_disconnected_chains(self):
        from app.core.operations import group_connected_edges
        edges = ["mesh.e[0]", "mesh.e[1]", "mesh.e[5]", "mesh.e[6]"]
        mock = _cmds()
        mock.polyInfo.return_value = [
            "EDGE 0: 0 1",   # chain A
            "EDGE 1: 1 2",   # chain A
            "EDGE 5: 10 11", # chain B
            "EDGE 6: 11 12", # chain B
        ]
        with patch("app.core.operations.cmds", mock):
            groups = group_connected_edges(edges)
        assert len(groups) == 2

    def test_empty_edge_list(self):
        from app.core.operations import group_connected_edges
        mock = _cmds()
        mock.polyInfo.return_value = []
        with patch("app.core.operations.cmds", mock):
            groups = group_connected_edges([])
        assert groups == []


# ---------------------------------------------------------------------------
# 3. group_has_branching
# ---------------------------------------------------------------------------

class TestGroupHasBranching:
    def _side_effect(self, info_map):
        """Return a polyInfo side effect that maps edge str → info list."""
        def _fn(edge, **kwargs):
            return info_map[edge]
        return _fn

    def test_false_for_simple_path(self):
        from app.core.operations import group_has_branching
        edges = ["mesh.e[0]", "mesh.e[1]", "mesh.e[2]"]
        mock = _cmds()
        mock.polyInfo.side_effect = self._side_effect({
            "mesh.e[0]": ["EDGE 0: 0 1"],
            "mesh.e[1]": ["EDGE 1: 1 2"],
            "mesh.e[2]": ["EDGE 2: 2 3"],
        })
        with patch("app.core.operations.cmds", mock):
            assert group_has_branching(edges) is False

    def test_true_when_vertex_shared_by_three_edges(self):
        from app.core.operations import group_has_branching
        # v1 appears 3 times → branching
        edges = ["mesh.e[0]", "mesh.e[1]", "mesh.e[2]"]
        mock = _cmds()
        mock.polyInfo.side_effect = self._side_effect({
            "mesh.e[0]": ["EDGE 0: 0 1"],
            "mesh.e[1]": ["EDGE 1: 1 2"],
            "mesh.e[2]": ["EDGE 2: 1 3"],  # v1 appears a third time
        })
        with patch("app.core.operations.cmds", mock):
            assert group_has_branching(edges) is True


# ---------------------------------------------------------------------------
# 4. create_control_from_curves
# ---------------------------------------------------------------------------

class TestCreateControlFromCurves:
    def test_captures_shapes_from_each_transform(self):
        from app.core.operations import create_control_from_curves

        mock_ctrl = MagicMock()
        mock_ctrl.get_all_shapes_data.return_value = [
            {"cv_positions": [[0, 0, 0], [1, 0, 0]], "degree": 1}
        ]

        with patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            ctrl, shapes = create_control_from_curves(["transform1", "transform2"])

        assert len(shapes) == 2  # one shape per transform
        assert ctrl is mock_ctrl  # first transform's Control instance

    def test_empty_list_returns_none_ctrl(self):
        from app.core.operations import create_control_from_curves

        with patch("app.core.operations.Control"):
            ctrl, shapes = create_control_from_curves([])

        assert ctrl is None
        assert shapes == []


# ---------------------------------------------------------------------------
# 5. create_control_from_edges
# ---------------------------------------------------------------------------

class TestCreateControlFromEdges:
    def test_raises_when_all_groups_fail(self):
        from app.core.operations import create_control_from_edges
        edges = ["mesh.e[0]"]
        mock = _cmds()
        # polyInfo for group_connected_edges
        mock.polyInfo.return_value = ["EDGE 0: 0 1"]
        # group_has_branching: returns False so polyToCurve path is taken
        mock.polyToCurve.side_effect = Exception("fail")
        mock.listRelatives.return_value = []

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control"):
            with pytest.raises(RuntimeError, match="Could not convert"):
                create_control_from_edges(edges)

    def test_succeeds_with_non_branching_group(self):
        from app.core.operations import create_control_from_edges
        edges = ["mesh.e[0]", "mesh.e[1]"]
        mock = _cmds()
        # group_connected_edges: two edges in one chain
        mock.polyInfo.return_value = [
            "EDGE 0: 0 1",
            "EDGE 1: 1 2",
        ]
        mock.polyToCurve.return_value = ["curve_node"]
        mock.listRelatives.return_value = ["shapeA"]

        mock_ctrl = MagicMock()
        mock_ctrl.get_all_shapes_data.return_value = [
            {"cv_positions": [[0, 0, 0], [1, 0, 0]], "degree": 1}
        ]

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control", return_value=mock_ctrl):
            ctrl, shapes = create_control_from_edges(edges)

        assert ctrl is mock_ctrl
        assert len(shapes) == 1


# ---------------------------------------------------------------------------
# 6. replace_control
# ---------------------------------------------------------------------------

class TestReplaceControl:
    def test_swaps_shapes(self):
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]

        shape = {
            "label": "my_shape",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": None,
        }

        mock_ctrl_inst = MagicMock()
        mock_ctrl_inst.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl_inst
            MockControl.create_from_db.return_value = "temp_node"
            replace_control("my_ctrl", shape)

        # Old shapes should have been deleted
        mock.delete.assert_called()

    def test_applies_color_when_stored(self):
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]

        shape = {
            "label": "colored",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": "[1.0, 0.5, 0.0]",
        }

        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            replace_control("my_ctrl", shape)

        # set_color should be called with the decoded rgb tuple
        mock_ctrl.set_color.assert_called_once_with((1.0, 0.5, 0.0))


# ---------------------------------------------------------------------------
# 7. rotate_control_cvs
# ---------------------------------------------------------------------------

class TestRotateControlCvs:
    def test_calls_rotate_on_all_cvs(self):
        from app.core.operations import rotate_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["curveShape1"]
        mock.ls.return_value = ["curveShape1.cv[0]", "curveShape1.cv[1]"]

        with patch("app.core.operations.cmds", mock):
            rotate_control_cvs("my_ctrl", "x", 90.0)

        mock.rotate.assert_called_once_with(
            90.0, 0.0, 0.0,
            ["curveShape1.cv[0]", "curveShape1.cv[1]"],
            objectSpace=True, relative=True,
        )

    def test_y_axis(self):
        from app.core.operations import rotate_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]"]

        with patch("app.core.operations.cmds", mock):
            rotate_control_cvs("ctrl", "y", 45.0)

        mock.rotate.assert_called_once_with(
            0.0, 45.0, 0.0,
            ["shape1.cv[0]"],
            objectSpace=True, relative=True,
        )

    def test_noop_when_no_shapes(self):
        from app.core.operations import rotate_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = []

        with patch("app.core.operations.cmds", mock):
            rotate_control_cvs("empty_ctrl", "z", 90.0)

        mock.rotate.assert_not_called()
