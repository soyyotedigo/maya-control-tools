"""Tests for Control operations — no Maya required.

Uses ``patch("app.core.control.cmds")`` to mock the module-level
``cmds`` reference inside control.py, so the tests run without a live
Maya session.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure the Maya mock is injected before we import anything that
# references maya.cmds (e.g. app.core.control at module level).
import app.compat  # noqa: F401 — side-effect: calls ensure_maya_mock() path
app.compat.ensure_maya_mock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmds(
    *,
    listRelatives: list | None = None,
    ls: list | None = None,
    xform: list | None = None,
    getAttr: int = 1,
    exactWorldBoundingBox: list | None = None,
    curve: str = "mock_CTRL",
    circle: tuple = ("mock_circle_CTRL", "makeNurbCircle1"),
) -> MagicMock:
    """Build a MagicMock for maya.cmds with sensible per-test defaults."""
    m = MagicMock()
    m.listRelatives.return_value = listRelatives if listRelatives is not None else []
    m.ls.return_value = ls if ls is not None else []
    m.xform.return_value = xform if xform is not None else [0.0, 0.0, 0.0]
    m.getAttr.return_value = getAttr
    m.exactWorldBoundingBox.return_value = (
        exactWorldBoundingBox if exactWorldBoundingBox is not None else [0, 0, 0, 1, 1, 1]
    )
    m.curve.return_value = curve
    m.circle.return_value = circle
    return m


# ---------------------------------------------------------------------------
# Control.create_from_db
# ---------------------------------------------------------------------------

class TestCreateFromDb:
    def test_flat_cv_data_calls_curve(self):
        """create_from_db should call cmds.curve with the stored cv list."""
        from app.core.control import Control

        shape = {
            "label": "triangle",
            "cv_data": json.dumps([[0, 0, 0], [1, 0, 0], [0.5, 1, 0]]),
            "degree": 1,
            "knots": None,
        }
        mock = _cmds(curve="triangle_CTRL")

        with patch("app.core.control.cmds", mock):
            node = Control.create_from_db(shape)

        assert node == "triangle_CTRL"
        mock.curve.assert_called_once()
        kwargs = mock.curve.call_args.kwargs
        assert kwargs["degree"] == 1
        assert kwargs["point"] == [[0, 0, 0], [1, 0, 0], [0.5, 1, 0]]

    def test_none_cv_data_uses_circle(self):
        """create_from_db should use cmds.circle when cv_data is None."""
        from app.core.control import Control

        shape = {
            "label": "my_circle",
            "cv_data": None,
            "degree": 3,
            "knots": None,
        }
        mock = _cmds(circle=("my_circle_CTRL", "makeNurbCircle1"))

        with patch("app.core.control.cmds", mock):
            node = Control.create_from_db(shape)

        assert node == "my_circle_CTRL"
        mock.circle.assert_called_once()
        mock.curve.assert_not_called()

    def test_v1_dict_format(self):
        """create_from_db should unwrap the v1 dict format before calling cmds.curve."""
        from app.core.control import Control

        cv_data = {"v": 1, "cv": [[0, 0, 0], [1, 0, 0]], "form": 0}
        shape = {
            "label": "v1_shape",
            "cv_data": json.dumps(cv_data),
            "degree": 1,
            "knots": None,
        }
        mock = _cmds(curve="v1_shape_CTRL")

        with patch("app.core.control.cmds", mock):
            node = Control.create_from_db(shape)

        assert node == "v1_shape_CTRL"
        kwargs = mock.curve.call_args.kwargs
        assert kwargs["point"] == [[0, 0, 0], [1, 0, 0]]

    def test_knots_passed_only_when_length_correct(self):
        """Knots are forwarded only when len(knots) == len(cvs) + degree - 1."""
        from app.core.control import Control

        cvs = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]  # 3 CVs, degree 1 → need 3 knots
        correct_knots = [0, 1, 2]
        shape = {
            "label": "knotted",
            "cv_data": json.dumps(cvs),
            "degree": 1,
            "knots": json.dumps(correct_knots),
        }
        mock = _cmds(curve="knotted_CTRL")

        with patch("app.core.control.cmds", mock):
            Control.create_from_db(shape)

        kwargs = mock.curve.call_args.kwargs
        assert kwargs.get("knot") == correct_knots

    def test_wrong_knot_length_omitted(self):
        """Knots with wrong length must NOT be forwarded to cmds.curve."""
        from app.core.control import Control

        cvs = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]
        bad_knots = [0, 1]   # wrong: need 3
        shape = {
            "label": "bad_knots",
            "cv_data": json.dumps(cvs),
            "degree": 1,
            "knots": json.dumps(bad_knots),
        }
        mock = _cmds(curve="bad_knots_CTRL")

        with patch("app.core.control.cmds", mock):
            Control.create_from_db(shape)

        kwargs = mock.curve.call_args.kwargs
        assert "knot" not in kwargs


# ---------------------------------------------------------------------------
# Control.set_color / reset_color
# ---------------------------------------------------------------------------

class TestColor:
    def test_set_color_enables_override_on_all_shapes(self):
        """set_color must set overrideEnabled + RGB attributes on every shape."""
        from app.core.control import Control

        mock = _cmds(listRelatives=["shapeA", "shapeB"])
        ctrl = Control(name="arm_ctrl")

        with patch("app.core.control.cmds", mock):
            ctrl.set_color((1.0, 0.5, 0.0))

        expected = [
            call("shapeA.overrideEnabled", True),
            call("shapeA.overrideRGBColors", True),
            call("shapeA.overrideColorR", 1.0),
            call("shapeA.overrideColorG", 0.5),
            call("shapeA.overrideColorB", 0.0),
            call("shapeB.overrideEnabled", True),
            call("shapeB.overrideRGBColors", True),
            call("shapeB.overrideColorR", 1.0),
            call("shapeB.overrideColorG", 0.5),
            call("shapeB.overrideColorB", 0.0),
        ]
        mock.setAttr.assert_has_calls(expected, any_order=False)

    def test_set_color_no_shapes_is_noop(self):
        """set_color with no shapes should not call setAttr at all."""
        from app.core.control import Control

        mock = _cmds(listRelatives=[])
        ctrl = Control(name="empty_ctrl")

        with patch("app.core.control.cmds", mock):
            ctrl.set_color((1.0, 0.0, 0.0))

        mock.setAttr.assert_not_called()

    def test_reset_color_disables_override(self):
        """reset_color must set overrideEnabled=False for each shape."""
        from app.core.control import Control

        mock = _cmds(listRelatives=["shapeX"])
        ctrl = Control(name="my_ctrl")

        with patch("app.core.control.cmds", mock):
            ctrl.reset_color()

        mock.setAttr.assert_called_once_with("shapeX.overrideEnabled", False)


# ---------------------------------------------------------------------------
# Control.get_bounding_box / get_dimensions / get_scale_factor
# ---------------------------------------------------------------------------

class TestGeometry:
    def test_get_bounding_box(self):
        from app.core.control import Control

        mock = _cmds(exactWorldBoundingBox=[-1, -1, -1, 1, 1, 1])
        ctrl = Control(name="box_ctrl")

        with patch("app.core.control.cmds", mock):
            bb = ctrl.get_bounding_box()

        assert bb == [-1, -1, -1, 1, 1, 1]

    def test_get_dimensions(self):
        from app.core.control import Control

        mock = _cmds(exactWorldBoundingBox=[0, 0, 0, 2, 4, 6])
        ctrl = Control(name="box_ctrl")

        with patch("app.core.control.cmds", mock):
            dims = ctrl.get_dimensions()

        assert dims == (2, 4, 6)

    def test_get_scale_factor_zero_when_zero_dim(self):
        """Scale factor is 0 when the bounding box is degenerate."""
        from app.core.control import Control

        mock = _cmds(exactWorldBoundingBox=[0, 0, 0, 0, 0, 0])
        ctrl = Control(name="flat_ctrl")

        with patch("app.core.control.cmds", mock):
            factor = ctrl.get_scale_factor()

        assert factor == 0.0

    def test_get_scale_factor_normalizes(self):
        from app.core.control import Control

        mock = _cmds(exactWorldBoundingBox=[0, 0, 0, 4, 2, 1])
        ctrl = Control(name="rect_ctrl")

        with patch("app.core.control.cmds", mock):
            factor = ctrl.get_scale_factor()

        assert abs(factor - 0.25) < 1e-9   # 1 / 4


# ---------------------------------------------------------------------------
# Control.to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_keys_present(self):
        """to_dict must return all required keys."""
        from app.core.control import Control

        mock = _cmds(
            listRelatives=["curveShape1"],
            ls=["curveShape1.cv[0]", "curveShape1.cv[1]"],
            xform=[1.0, 2.0, 3.0],
            getAttr=1,
            exactWorldBoundingBox=[-1, -1, -1, 1, 1, 1],
        )
        ctrl = Control(name="arm_ctrl")

        with patch("app.core.control.cmds", mock):
            d = ctrl.to_dict()

        assert set(d) == {"name", "cv_positions", "cv_count", "degree", "knots",
                          "position", "bounding_box"}
        assert d["name"] == "arm_ctrl"
        assert d["cv_count"] == 2


# ---------------------------------------------------------------------------
# Control.from_selection
# ---------------------------------------------------------------------------

class TestFromSelection:
    def test_raises_when_nothing_selected(self):
        from app.core.control import Control

        mock = _cmds(ls=[])

        with patch("app.core.control.cmds", mock):
            with pytest.raises(RuntimeError, match="Nothing selected"):
                Control.from_selection()

    def test_returns_control_wrapping_first_node(self):
        from app.core.control import Control

        mock = _cmds(ls=["leg_CTRL", "arm_CTRL"])

        with patch("app.core.control.cmds", mock):
            ctrl = Control.from_selection()

        assert ctrl.name == "leg_CTRL"
