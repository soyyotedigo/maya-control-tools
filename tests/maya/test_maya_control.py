"""
Real Maya integration tests for app.core.control.Control.

Requires mayapy:
    mayapy -m pytest tests/maya/test_maya_control.py -v
"""
import pytest
import maya.cmds as cmds

from app.core.control import Control


class TestControlCreate:
    def test_transform_exists_in_scene(self, empty_scene):
        """Control.create_from_db with a circle shape dict must produce a Maya transform."""
        circle = cmds.circle(name="src")[0]
        src_ctrl = Control(name=circle)
        shape_dict = {
            "name": "circle",
            "label": "Circle",
            "shapes": src_ctrl.get_all_shapes_data(),
        }
        node = Control.create_from_db(shape_dict)
        assert cmds.objExists(node), "Created control transform must exist in scene"
        shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve") or []
        assert len(shapes) > 0, "Created node must have at least one nurbsCurve shape"


class TestControlSetColor:
    def test_override_color_rgb_attribute(self, empty_scene):
        """set_color must set overrideColorRGB on curve shapes."""
        circle = cmds.circle(name="color_ctrl")[0]
        ctrl = Control(name=circle)
        ctrl.set_color((1.0, 0.0, 0.0))

        shape = cmds.listRelatives(circle, shapes=True)[0]
        assert cmds.getAttr(f"{shape}.overrideEnabled") == 1
        rgb = cmds.getAttr(f"{shape}.overrideColorRGB")[0]
        assert abs(rgb[0] - 1.0) < 1e-4
        assert abs(rgb[1] - 0.0) < 1e-4
        assert abs(rgb[2] - 0.0) < 1e-4


class TestControlToDict:
    def test_to_dict_has_required_keys(self, empty_scene):
        """get_all_shapes_data must return dicts with cv_positions, degree, knots."""
        circle = cmds.circle(name="dict_ctrl")[0]
        ctrl = Control(name=circle)
        shapes_data = ctrl.get_all_shapes_data()
        assert len(shapes_data) > 0
        for sd in shapes_data:
            assert "cv_positions" in sd, "Missing cv_positions"
            assert "degree" in sd, "Missing degree"
            assert "knots" in sd, "Missing knots"

    def test_cv_positions_are_numeric(self, empty_scene):
        """Each CV position must be a sequence of three floats."""
        circle = cmds.circle(name="numeric_ctrl")[0]
        ctrl = Control(name=circle)
        shapes_data = ctrl.get_all_shapes_data()
        for sd in shapes_data:
            for pos in sd["cv_positions"]:
                assert len(pos) == 3
                for v in pos:
                    assert isinstance(v, (int, float))


class TestControlCreateFromDb:
    def test_curve_has_correct_cv_count(self, empty_scene):
        """create_from_db must reproduce the exact CV count from shapes_data."""
        circle = cmds.circle(name="cv_src", sections=8)[0]
        src_shape = cmds.listRelatives(circle, shapes=True)[0]
        expected_cv_count = len(cmds.ls(f"{src_shape}.cv[*]", flatten=True))

        ctrl = Control(name=circle)
        shape_dict = {
            "name": "circle8",
            "label": "Circle 8",
            "shapes": ctrl.get_all_shapes_data(),
        }
        node = Control.create_from_db(shape_dict)
        new_shape = cmds.listRelatives(node, shapes=True, type="nurbsCurve")[0]
        actual_cv_count = len(cmds.ls(f"{new_shape}.cv[*]", flatten=True))
        assert actual_cv_count == expected_cv_count, (
            f"Expected {expected_cv_count} CVs, got {actual_cv_count}"
        )
