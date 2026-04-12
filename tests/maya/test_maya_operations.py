"""
Real Maya integration tests for app.core.operations.

Requires mayapy:
    mayapy -m pytest tests/maya/test_maya_operations.py -v
"""
import pytest
import maya.cmds as cmds

from app.core.operations import (
    create_control_from_edges,
    create_control_from_curves,
    replace_control,
    rotate_control_cvs,
    undo_chunk,
)


# ---------------------------------------------------------------------------
# rotate_control_cvs
# ---------------------------------------------------------------------------

class TestRotateControlCvs:
    def test_cvs_move_after_rotation(self, empty_scene):
        """Rotating CVs around Y must change their positions."""
        circle = cmds.circle(name="test_ctrl", normal=(0, 1, 0))[0]
        shape = cmds.listRelatives(circle, shapes=True)[0]

        before = [
            cmds.xform(cv, q=True, objectSpace=True, translation=True)
            for cv in cmds.ls(f"{shape}.cv[*]", flatten=True)
        ]
        rotate_control_cvs(circle, "y", 90.0)
        after = [
            cmds.xform(cv, q=True, objectSpace=True, translation=True)
            for cv in cmds.ls(f"{shape}.cv[*]", flatten=True)
        ]
        assert before != after, "CV positions should change after rotation"

    def test_four_rotations_returns_to_original(self, empty_scene):
        """Four 90° rotations around Z must return CVs to their start positions."""
        circle = cmds.circle(name="test_ctrl", normal=(0, 0, 1))[0]
        shape = cmds.listRelatives(circle, shapes=True)[0]
        cvs = cmds.ls(f"{shape}.cv[*]", flatten=True)

        before = [cmds.xform(cv, q=True, objectSpace=True, translation=True) for cv in cvs]
        for _ in range(4):
            rotate_control_cvs(circle, "z", 90.0)
        after = [cmds.xform(cv, q=True, objectSpace=True, translation=True) for cv in cvs]

        for b, a in zip(before, after):
            assert abs(b[0] - a[0]) < 1e-3
            assert abs(b[1] - a[1]) < 1e-3
            assert abs(b[2] - a[2]) < 1e-3


# ---------------------------------------------------------------------------
# create_control_from_edges
# ---------------------------------------------------------------------------

class TestCreateControlFromEdges:
    def test_creates_nurbs_curve(self, empty_scene):
        """A cube's edges should produce a transform with nurbsCurve shapes."""
        cube = cmds.polyCube()[0]
        edges = cmds.filterExpand(f"{cube}.e[*]", selectionMask=32, expand=True)
        ctrl, shapes_data = create_control_from_edges(edges)
        assert ctrl is not None
        shapes = cmds.listRelatives(ctrl.name, shapes=True, type="nurbsCurve") or []
        assert len(shapes) > 0, "Expected at least one nurbsCurve shape"

    def test_shapes_data_populated(self, empty_scene):
        """shapes_data must contain cv_positions, degree, and knots for each shape."""
        cube = cmds.polyCube()[0]
        edges = cmds.filterExpand(f"{cube}.e[*]", selectionMask=32, expand=True)
        _, shapes_data = create_control_from_edges(edges)
        assert len(shapes_data) > 0
        for sd in shapes_data:
            assert "cv_positions" in sd
            assert "degree" in sd
            assert "knots" in sd


# ---------------------------------------------------------------------------
# replace_control
# ---------------------------------------------------------------------------

class TestReplaceControl:
    def test_cv_count_changes(self, empty_scene):
        """Replacing a circle with a square should change the CV count."""
        circle = cmds.circle(name="original_ctrl", sections=8)[0]
        circle_shape = cmds.listRelatives(circle, shapes=True)[0]
        cv_count_before = len(cmds.ls(f"{circle_shape}.cv[*]", flatten=True))

        # Build a square-ish shape with a different CV count.
        square = cmds.circle(name="square_src", sections=4)[0]
        from app.core.control import Control
        square_ctrl = Control(name=square)
        shape_dict = {"name": "square", "label": "Square", "shapes": square_ctrl.get_all_shapes_data()}

        replace_control(circle, shape_dict)
        new_shapes = cmds.listRelatives(circle, shapes=True, type="nurbsCurve") or []
        assert len(new_shapes) > 0, "Replaced control must still have curve shapes"
        cv_count_after = len(cmds.ls(f"{new_shapes[0]}.cv[*]", flatten=True))
        assert cv_count_before != cv_count_after, "CV count should differ after replace"

    def test_transform_node_preserved(self, empty_scene):
        """The original transform node must survive shape replacement."""
        circle = cmds.circle(name="keep_me")[0]
        square = cmds.circle(name="src_shape", sections=4)[0]
        from app.core.control import Control
        square_ctrl = Control(name=square)
        shape_dict = {"name": "square", "label": "Square", "shapes": square_ctrl.get_all_shapes_data()}

        replace_control(circle, shape_dict)
        assert cmds.objExists("keep_me"), "Original transform must still exist"


# ---------------------------------------------------------------------------
# create_control_from_curves
# ---------------------------------------------------------------------------

class TestCreateControlFromCurves:
    def test_captures_shapes_data(self, empty_scene):
        """Capturing a NURBS circle must produce non-empty shapes_data."""
        circle = cmds.circle(name="src_circle")[0]
        ctrl, shapes_data = create_control_from_curves([circle])
        assert ctrl is not None
        assert len(shapes_data) > 0

    def test_shapes_data_has_required_keys(self, empty_scene):
        circle = cmds.circle(name="src_circle")[0]
        _, shapes_data = create_control_from_curves([circle])
        for sd in shapes_data:
            assert "cv_positions" in sd
            assert "degree" in sd
            assert "knots" in sd


# ---------------------------------------------------------------------------
# undo_chunk
# ---------------------------------------------------------------------------

class TestUndoChunk:
    def test_undo_chunk_pairs_info_calls(self, empty_scene):
        """undo_chunk must open and close an undo chunk without raising."""
        with undo_chunk("test_chunk"):
            cmds.sphere(name="undo_test_sphere")
        assert cmds.objExists("undo_test_sphere")

    def test_undo_removes_node(self, empty_scene):
        """Objects created inside undo_chunk must be removable with one undo."""
        with undo_chunk("create_sphere"):
            cmds.sphere(name="undo_sphere")
        assert cmds.objExists("undo_sphere")
        cmds.undo()
        assert not cmds.objExists("undo_sphere"), "Undo should remove the sphere"
