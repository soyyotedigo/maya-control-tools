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

    def test_replace_color_false_preserves_rgb_override(self):
        """When replace_color=False, the full set of color override attrs is
        re-applied via setAttr — covers both RGB and index-based colors."""
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        # Original control: green RGB override.
        mock.getAttr.side_effect = lambda attr: {
            "oldShape.overrideEnabled":   True,
            "oldShape.overrideRGBColors": True,
            "oldShape.overrideColor":     0,
            "oldShape.overrideColorR":    0.0,
            "oldShape.overrideColorG":    1.0,
            "oldShape.overrideColorB":    0.0,
        }.get(attr, 0)

        shape = {
            "label": "circle",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": "[1.0, 0.0, 0.0]",  # library red — must NOT be applied
        }

        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            replace_control("my_ctrl", shape, replace_color=False)

        # Library color must NOT have been applied via ctrl.set_color.
        mock_ctrl.set_color.assert_not_called()
        # Green channel must have been written back via setAttr.
        mock.setAttr.assert_any_call("oldShape.overrideColorG", 1.0)

    def test_replace_color_false_preserves_index_override(self):
        """Index-based colors (overrideRGBColors=False) are also preserved."""
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        # Index-based yellow (index 17 in Maya's palette).
        mock.getAttr.side_effect = lambda attr: {
            "oldShape.overrideEnabled":   True,
            "oldShape.overrideRGBColors": False,
            "oldShape.overrideColor":     17,
            "oldShape.overrideColorR":    0.0,
            "oldShape.overrideColorG":    0.0,
            "oldShape.overrideColorB":    0.0,
        }.get(attr, 0)

        shape = {
            "label": "box",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": None,
        }

        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            replace_control("my_ctrl", shape, replace_color=False)

        mock_ctrl.set_color.assert_not_called()
        mock.setAttr.assert_any_call("oldShape.overrideColor", 17)

    def test_replace_name_renames_node(self):
        """When replace_name=True, the transform is renamed to the shape label."""
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        mock.rename.return_value = "arrow_CTRL"

        shape = {
            "label": "arrow CTRL",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": None,
        }

        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            final = replace_control("old_node", shape, replace_name=True)

        mock.rename.assert_called_once_with("old_node", "arrow_CTRL")
        assert final == "arrow_CTRL"

    def test_replace_name_false_skips_rename(self):
        from app.core.operations import replace_control

        mock = _cmds()
        mock.listRelatives.return_value = ["oldShape"]
        mock.ls.return_value = ["oldShape.cv[0]"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]

        shape = {"label": "circle", "cv_data": "[[0,0,0]]", "degree": 1, "knots": None, "color": None}
        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            final = replace_control("my_ctrl", shape, replace_name=False)

        mock.rename.assert_not_called()
        assert final == "my_ctrl"


# ---------------------------------------------------------------------------
# 6b. replace_controls_in_selection
# ---------------------------------------------------------------------------

class TestReplaceControlsInSelection:
    def test_restores_maya_selection_after_replace(self):
        """Control.create_from_db auto-selects the temp node, then deleting it
        clears the selection. replace_controls_in_selection must restore the
        original selection so subsequent scale / rotate ops still work."""
        from app.core.operations import replace_controls_in_selection

        mock = _cmds()
        mock.ls.return_value = ["arm_ctrl"]
        mock.listRelatives.return_value = ["oldShape"]
        mock.xform.return_value = [0.0, 0.0, 0.0]
        mock.exactWorldBoundingBox.return_value = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]

        shape = {
            "label": "circle",
            "cv_data": "[[0,0,0],[1,0,0]]",
            "degree": 1,
            "knots": None,
            "color": None,
        }

        mock_ctrl = MagicMock()
        mock_ctrl.get_max_dimension.return_value = 1.0

        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.Control") as MockControl:
            MockControl.return_value = mock_ctrl
            MockControl.create_from_db.return_value = "temp_node"
            replace_controls_in_selection(shape)

        mock.select.assert_called_with(["arm_ctrl"])

    def test_returns_zero_when_nothing_selected(self):
        from app.core.operations import replace_controls_in_selection
        mock = _cmds()
        mock.ls.return_value = []

        with patch("app.core.operations.cmds", mock):
            assert replace_controls_in_selection({}) == 0

        mock.select.assert_not_called()


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


# ---------------------------------------------------------------------------
# 8. scale_control_cvs
# ---------------------------------------------------------------------------

class TestScaleControlCvs:
    def test_calls_scale_on_all_cvs(self):
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["curveShape1"]
        mock.ls.return_value = ["curveShape1.cv[0]", "curveShape1.cv[1]"]

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("my_ctrl", 1.5)

        mock.scale.assert_called_once_with(
            1.5, 1.5, 1.5,
            ["curveShape1.cv[0]", "curveShape1.cv[1]"],
            objectSpace=True, relative=True,
        )

    def test_scale_down(self):
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]"]

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("ctrl", 0.5)

        mock.scale.assert_called_once_with(
            0.5, 0.5, 0.5,
            ["shape1.cv[0]"],
            objectSpace=True, relative=True,
        )

    def test_noop_when_no_shapes(self):
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = []

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("empty_ctrl", 2.0)

        mock.scale.assert_not_called()

    def test_axes_scales_only_listed_axes(self):
        """A gated scale leaves the omitted axes at 1.0."""
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]"]

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("ctrl", 2.0, axes="xz")

        mock.scale.assert_called_once_with(
            2.0, 1.0, 2.0,
            ["shape1.cv[0]"],
            objectSpace=True, relative=True,
        )

    def test_from_center_scales_about_centroid(self):
        """from_center moves CVs about their mean, leaving that point fixed."""
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]", "shape1.cv[1]"]
        reads = {"shape1.cv[0]": [0.0, 0.0, 0.0],
                 "shape1.cv[1]": [2.0, 0.0, 0.0]}
        writes: dict[str, list] = {}

        def xform(cv, **kw):
            if kw.get("query"):
                return list(reads[cv])
            writes[cv] = list(kw["translation"])
        mock.xform.side_effect = xform

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("ctrl", 2.0, from_center=True)

        # centroid is (1, 0, 0); factor 2 reflects each CV to twice its offset
        assert writes["shape1.cv[0]"] == [-1.0, 0.0, 0.0]
        assert writes["shape1.cv[1]"] == [3.0, 0.0, 0.0]
        mock.scale.assert_not_called()  # never the pivot path

    def test_from_center_respects_axis_gate(self):
        """A gated from_center scale leaves omitted axes untouched."""
        from app.core.operations import scale_control_cvs
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]", "shape1.cv[1]"]
        reads = {"shape1.cv[0]": [0.0, 2.0, 0.0],
                 "shape1.cv[1]": [2.0, 4.0, 0.0]}
        writes: dict[str, list] = {}

        def xform(cv, **kw):
            if kw.get("query"):
                return list(reads[cv])
            writes[cv] = list(kw["translation"])
        mock.xform.side_effect = xform

        with patch("app.core.operations.cmds", mock):
            scale_control_cvs("ctrl", 2.0, axes="x", from_center=True)

        # centroid (1, 3, 0); only X scales, Y/Z keep their original values
        assert writes["shape1.cv[0]"] == [-1.0, 2.0, 0.0]
        assert writes["shape1.cv[1]"] == [3.0, 4.0, 0.0]


# ---------------------------------------------------------------------------
# 9. scale_selected_cvs
# ---------------------------------------------------------------------------

class TestScaleSelectedCvs:
    def test_scales_each_selected_node(self):
        from app.core.operations import scale_selected_cvs
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a", "ctrl_b"]
        mock.listRelatives.return_value = ["shape1"]

        with patch("app.core.operations.cmds", mock):
            count = scale_selected_cvs(1.25)

        assert count == 2
        # scale was called once per selected control (each had one shape)
        assert mock.scale.call_count == 2

    def test_returns_zero_when_nothing_selected(self):
        from app.core.operations import scale_selected_cvs
        mock = _cmds()
        mock.ls.return_value = []

        with patch("app.core.operations.cmds", mock):
            count = scale_selected_cvs(1.5)

        assert count == 0
        mock.scale.assert_not_called()

    def test_returns_zero_when_factor_is_identity(self):
        """A factor of 1.0 is a no-op — no scale calls and no chunk."""
        from app.core.operations import scale_selected_cvs
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a"]

        with patch("app.core.operations.cmds", mock):
            count = scale_selected_cvs(1.0)

        assert count == 0
        mock.scale.assert_not_called()

    def test_axes_forwarded_to_each_node(self):
        """A gated selection scale only touches the requested axes."""
        from app.core.operations import scale_selected_cvs
        mock = _cmds()
        mock.ls.side_effect = lambda *a, **k: (
            ["ctrl_a"] if k.get("selection") else ["shape1.cv[0]"]
        )
        mock.listRelatives.return_value = ["shape1"]

        with patch("app.core.operations.cmds", mock):
            count = scale_selected_cvs(2.0, axes="z")

        assert count == 1
        mock.scale.assert_called_once_with(
            1.0, 1.0, 2.0,
            ["shape1.cv[0]"],
            objectSpace=True, relative=True,
        )

    def test_from_center_forwarded_to_each_node(self):
        """from_center reaches scale_control_cvs for every selected node."""
        from app.core import operations
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a", "ctrl_b"]
        with patch("app.core.operations.cmds", mock), \
             patch("app.core.operations.scale_control_cvs") as scaler:
            count = operations.scale_selected_cvs(1.5, from_center=True)

        assert count == 2
        for node in ("ctrl_a", "ctrl_b"):
            scaler.assert_any_call(node, 1.5, axes="xyz", from_center=True)

    def test_empty_axes_is_noop(self):
        """No ticked axes → nothing is scaled."""
        from app.core.operations import scale_selected_cvs
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a"]

        with patch("app.core.operations.cmds", mock):
            count = scale_selected_cvs(2.0, axes="")

        assert count == 0
        mock.scale.assert_not_called()


# ---------------------------------------------------------------------------
# 9b. Mirror
# ---------------------------------------------------------------------------

def _mirror_cmds(selection, targets, shapes, cvs, positions):
    """Build a cmds mock for mirror tests.

    selection : list of selected long paths
    targets   : {short counterpart name: [matching long paths]}
    shapes    : {transform path: [shape names]}
    cvs       : {"shape.cv[*]": [cv names]}
    positions : {cv name: [x, y, z]}  (returned for any xform query)
    Returns (mock, writes) where writes records xform set translations.
    """
    m = MagicMock()

    def ls(*a, **k):
        if k.get("selection"):
            return list(selection)
        if a and isinstance(a[0], str) and a[0].endswith(".cv[*]"):
            return list(cvs.get(a[0], []))
        if a:
            return list(targets.get(a[0], []))
        return []
    m.ls.side_effect = ls
    m.listRelatives.side_effect = lambda node, **k: list(shapes.get(node, []))

    writes: dict[str, list] = {}

    def xform(cv, **k):
        if k.get("query"):
            return list(positions[cv])
        writes[cv] = list(k["translation"])
    m.xform.side_effect = xform
    return m, writes


class TestMirrorName:
    def test_recognises_side_tokens(self):
        from app.core.operations import mirror_name
        assert mirror_name("arm_L_ctl") == "arm_R_ctl"
        assert mirror_name("arm_R_ctl") == "arm_L_ctl"
        assert mirror_name("L_arm") == "R_arm"
        assert mirror_name("arm_L") == "arm_R"
        assert mirror_name("LeftHand") == "RightHand"

    def test_strips_dag_path(self):
        from app.core.operations import mirror_name
        assert mirror_name("|grp|arm_l_ctl") == "arm_r_ctl"

    def test_returns_none_without_side_token(self):
        from app.core.operations import mirror_name
        assert mirror_name("spine_ctl") is None
        assert mirror_name("center_M_ctl") is None


class TestMirrorSelectedControls:
    def test_mirror_to_opposite_side(self):
        from app.core import operations
        m, writes = _mirror_cmds(
            selection=["|grp|arm_L_ctl"],
            targets={"arm_R_ctl": ["|grp|arm_R_ctl"]},
            shapes={"|grp|arm_L_ctl": ["L_shape"],
                    "|grp|arm_R_ctl": ["R_shape"]},
            cvs={"L_shape.cv[*]": ["Ls0", "Ls1"],
                 "R_shape.cv[*]": ["Rs0", "Rs1"]},
            positions={"Ls0": [1.0, 2.0, 3.0], "Ls1": [4.0, 5.0, 6.0]},
        )
        with patch("app.core.operations.cmds", m):
            result = operations.mirror_selected_controls("x")

        assert result == (1, 0, 0)
        # World X negated, written onto the matching counterpart CVs.
        assert writes["Rs0"] == [-1.0, 2.0, 3.0]
        assert writes["Rs1"] == [-4.0, 5.0, 6.0]

    def test_flip_in_place_when_no_counterpart(self):
        from app.core import operations
        m, writes = _mirror_cmds(
            selection=["|grp|spine_ctl"],
            targets={},
            shapes={"|grp|spine_ctl": ["C_shape"]},
            cvs={"C_shape.cv[*]": ["c0", "c1"]},
            positions={"c0": [1.0, 2.0, 3.0], "c1": [-4.0, 5.0, 6.0]},
        )
        with patch("app.core.operations.cmds", m):
            result = operations.mirror_selected_controls("x")

        assert result == (0, 1, 0)
        assert writes["c0"] == [-1.0, 2.0, 3.0]
        assert writes["c1"] == [4.0, 5.0, 6.0]

    def test_rebuilds_on_topology_mismatch(self):
        """Different L/R shapes -> rebuild the opposite, not skip."""
        from app.core import operations
        m, writes = _mirror_cmds(
            selection=["|g|arm_L_ctl"],
            targets={"arm_R_ctl": ["|g|arm_R_ctl"]},
            shapes={"|g|arm_L_ctl": ["Ls"], "|g|arm_R_ctl": ["Rs"]},
            cvs={"Ls.cv[*]": ["a", "b", "c"], "Rs.cv[*]": ["x", "y"]},
            positions={"a": [1.0, 1.0, 1.0], "b": [2.0, 2.0, 2.0],
                       "c": [3.0, 3.0, 3.0]},
        )
        m.duplicate.return_value = ["dup"]
        m.getAttr.return_value = False  # no override colour / not intermediate
        with patch("app.core.operations.cmds", m):
            result = operations.mirror_selected_controls("x")

        assert result == (1, 0, 0)        # counted as mirrored, not skipped
        m.duplicate.assert_called_once()  # source was duplicated
        m.delete.assert_any_call(["Rs"])  # old opposite shapes removed

    def test_skips_ambiguous_counterpart(self):
        from app.core import operations
        m, writes = _mirror_cmds(
            selection=["|a|arm_L_ctl"],
            targets={"arm_R_ctl": ["|a|arm_R_ctl", "|b|arm_R_ctl"]},
            shapes={}, cvs={}, positions={},
        )
        with patch("app.core.operations.cmds", m):
            result = operations.mirror_selected_controls("x")

        assert result == (0, 0, 1)

    def test_empty_selection_returns_zeros(self):
        from app.core import operations
        m, _ = _mirror_cmds([], {}, {}, {}, {})
        with patch("app.core.operations.cmds", m):
            assert operations.mirror_selected_controls("x") == (0, 0, 0)

    def test_invalid_axis_returns_zeros(self):
        from app.core import operations
        m, _ = _mirror_cmds(["|g|arm_L_ctl"], {}, {}, {}, {})
        with patch("app.core.operations.cmds", m):
            assert operations.mirror_selected_controls("w") == (0, 0, 0)


# ---------------------------------------------------------------------------
# 9c. Viewport control colour
# ---------------------------------------------------------------------------

class TestControlColor:
    def test_set_color_overrides_each_shape(self):
        from app.core.operations import set_selected_controls_color
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a"]
        mock.listRelatives.return_value = ["shape1"]

        with patch("app.core.operations.cmds", mock):
            count = set_selected_controls_color((1.0, 0.5, 0.0))

        assert count == 1
        mock.setAttr.assert_any_call("shape1.overrideEnabled", True)
        mock.setAttr.assert_any_call("shape1.overrideRGBColors", True)
        mock.setAttr.assert_any_call("shape1.overrideColorR", 1.0)
        mock.setAttr.assert_any_call("shape1.overrideColorG", 0.5)
        mock.setAttr.assert_any_call("shape1.overrideColorB", 0.0)

    def test_set_color_returns_zero_when_nothing_selected(self):
        from app.core.operations import set_selected_controls_color
        mock = _cmds()
        mock.ls.return_value = []

        with patch("app.core.operations.cmds", mock):
            count = set_selected_controls_color((1.0, 0.0, 0.0))

        assert count == 0
        mock.setAttr.assert_not_called()

    def test_reset_color_disables_override(self):
        from app.core.operations import reset_selected_controls_color
        mock = _cmds()
        mock.ls.return_value = ["ctrl_a"]
        mock.listRelatives.return_value = ["shape1"]

        with patch("app.core.operations.cmds", mock):
            count = reset_selected_controls_color()

        assert count == 1
        mock.setAttr.assert_called_once_with("shape1.overrideEnabled", False)


# ---------------------------------------------------------------------------
# 10. snapshot_cv_positions / restore_cv_positions
# ---------------------------------------------------------------------------

class TestSnapshotCvPositions:
    def test_captures_all_cv_positions_per_shape(self):
        from app.core.operations import snapshot_cv_positions
        mock = _cmds()
        mock.listRelatives.return_value = ["shape1"]
        mock.ls.return_value = ["shape1.cv[0]", "shape1.cv[1]"]
        # Return a different position for each xform call.
        mock.xform.side_effect = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

        with patch("app.core.operations.cmds", mock):
            snap = snapshot_cv_positions("ctrl")

        assert snap == {"shape1": [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]}

    def test_returns_empty_when_no_curve_shapes(self):
        from app.core.operations import snapshot_cv_positions
        mock = _cmds()
        mock.listRelatives.return_value = None

        with patch("app.core.operations.cmds", mock):
            snap = snapshot_cv_positions("empty_ctrl")

        assert snap == {}


class TestRestoreCvPositions:
    def test_xforms_each_cv_to_snapshot_position(self):
        from app.core.operations import restore_cv_positions
        mock = _cmds()
        mock.ls.return_value = ["shape1.cv[0]", "shape1.cv[1]"]
        snapshot = {"shape1": [(2.0, 0.0, 0.0), (0.0, 2.0, 0.0)]}

        with patch("app.core.operations.cmds", mock):
            restore_cv_positions("ctrl", snapshot)

        # One xform query for the lookup (handled internally) is NOT used here —
        # we only restore via xform with translation= kwarg.
        translation_calls = [
            c for c in mock.xform.call_args_list if "translation" in c.kwargs
        ]
        assert len(translation_calls) == 2
        assert translation_calls[0].kwargs["translation"] == (2.0, 0.0, 0.0)
        assert translation_calls[1].kwargs["translation"] == (0.0, 2.0, 0.0)

    def test_skips_shape_when_cv_count_mismatches(self):
        from app.core.operations import restore_cv_positions
        mock = _cmds()
        # Snapshot has 3 CVs but the curve now has only 2 — skip.
        mock.ls.return_value = ["shape1.cv[0]", "shape1.cv[1]"]
        snapshot = {"shape1": [(0, 0, 0), (1, 0, 0), (2, 0, 0)]}

        with patch("app.core.operations.cmds", mock):
            restore_cv_positions("ctrl", snapshot)

        translation_calls = [
            c for c in mock.xform.call_args_list if "translation" in c.kwargs
        ]
        assert translation_calls == []

    def test_axes_restores_only_listed_components(self):
        """A gated restore keeps the current X/Z and only resets Y."""
        from app.core.operations import restore_cv_positions
        mock = _cmds()
        mock.ls.return_value = ["shape1.cv[0]"]
        # Current CV sits at (5, 9, 7); snapshot Y was 2.
        mock.xform.return_value = [5.0, 9.0, 7.0]
        snapshot = {"shape1": [(1.0, 2.0, 3.0)]}

        with patch("app.core.operations.cmds", mock):
            restore_cv_positions("ctrl", snapshot, axes="y")

        set_calls = [
            c for c in mock.xform.call_args_list
            if "translation" in c.kwargs and not c.kwargs.get("query")
        ]
        assert len(set_calls) == 1
        assert set_calls[0].kwargs["translation"] == [5.0, 2.0, 7.0]


# ---------------------------------------------------------------------------
# 11. ensure_snapshots_for_selection / reset_selected_cvs
# ---------------------------------------------------------------------------

class TestEnsureSnapshotsForSelection:
    def test_adds_entries_for_missing_nodes_only(self):
        from app.core.operations import ensure_snapshots_for_selection
        mock = _cmds()
        mock.ls.side_effect = lambda *a, **kw: (
            ["ctrl_a", "ctrl_b"] if kw.get("selection") else ["shape1.cv[0]"]
        )
        mock.listRelatives.return_value = ["shape1"]
        mock.xform.return_value = [0.0, 0.0, 0.0]

        # Snapshot key must match what listRelatives returns so it is not
        # considered stale (validation added for the Replace Control bug fix).
        existing_snap = {"shape1": [(0.0, 0.0, 0.0)]}
        snapshots = {"ctrl_a": existing_snap}

        with patch("app.core.operations.cmds", mock):
            ensure_snapshots_for_selection(snapshots)

        # ctrl_a was untouched; ctrl_b got a fresh snapshot.
        assert snapshots["ctrl_a"] is existing_snap
        assert "ctrl_b" in snapshots

    def test_invalidates_stale_snapshot_after_shape_replacement(self):
        """After Replace Control the old shape full-paths are gone.
        ensure_snapshots_for_selection must detect the mismatch and re-capture."""
        from app.core.operations import ensure_snapshots_for_selection
        mock = _cmds()
        mock.ls.side_effect = lambda *a, **kw: (
            ["ctrl_a"] if kw.get("selection") else ["new_shape.cv[0]"]
        )
        mock.listRelatives.return_value = ["new_shape"]
        mock.xform.return_value = [0.0, 0.0, 0.0]

        # Stale snapshot references the old shape node that no longer exists.
        snapshots = {"ctrl_a": {"old_shape": [(1.0, 0.0, 0.0)]}}

        with patch("app.core.operations.cmds", mock):
            ensure_snapshots_for_selection(snapshots)

        # Old shape key must be gone; new shape key must be present.
        assert "old_shape" not in snapshots["ctrl_a"]
        assert "new_shape" in snapshots["ctrl_a"]


class TestResetSelectedCvs:
    def test_restores_only_selected_nodes_with_snapshot(self):
        from app.core.operations import reset_selected_cvs
        mock = _cmds()
        mock.ls.side_effect = lambda *a, **kw: (
            ["ctrl_a", "ctrl_b"] if kw.get("selection") else ["shape1.cv[0]"]
        )
        # ctrl_b has no snapshot → must be skipped.
        snapshots = {"ctrl_a": {"shape1": [(1.0, 0.0, 0.0)]}}

        with patch("app.core.operations.cmds", mock):
            count = reset_selected_cvs(snapshots)

        assert count == 1
        translation_calls = [
            c for c in mock.xform.call_args_list if "translation" in c.kwargs
        ]
        assert len(translation_calls) == 1

    def test_returns_zero_when_no_snapshots_match(self):
        from app.core.operations import reset_selected_cvs
        mock = _cmds()
        mock.ls.return_value = ["ctrl_x"]

        with patch("app.core.operations.cmds", mock):
            count = reset_selected_cvs({"other_ctrl": {}})

        assert count == 0
