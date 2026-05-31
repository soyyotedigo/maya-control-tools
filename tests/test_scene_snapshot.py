"""Tests for ``app.core.scene_snapshot`` — no Maya required.

Patches ``app.core.scene_snapshot.cmds`` (and the ``Control`` it uses)
so the save/load round-trip can be exercised against an in-memory fake
scene.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# Inject the Maya mock so anything in the module path that imports
# ``maya.cmds`` at module level resolves to the stub.
import app.compat
app.compat.ensure_maya_mock()


# ---------------------------------------------------------------------------
# Fake scene fixture
# ---------------------------------------------------------------------------

class FakeScene:
    """Tiny scene model: transforms own one nurbsCurve shape, with attrs."""

    def __init__(self):
        # transform_long → {"shape": str, "color": dict|None, "trs": dict,
        #                    "locked": set[str]}
        self.transforms: dict[str, dict] = {}
        # attr full name (transform.attrName) → value
        self.attr_values: dict[str, object] = {}
        # transforms whose .translate/.rotate/.scale are returned as tuples
        # by getAttr (Maya returns a list containing one 3-tuple).

    # ---- scene authoring helpers -----------------------------------------
    def add_control(self, name: str, *, translate=(0, 0, 0), rotate=(0, 0, 0),
                    scale=(1, 1, 1), color: dict | None = None,
                    locked: set[str] | None = None):
        long_path = f"|{name}"
        shape = f"{long_path}|{name}Shape"
        self.transforms[long_path] = {
            "short":  name,
            "shape":  shape,
            "color":  color,
            "trs":    {"translate": list(translate),
                       "rotate":    list(rotate),
                       "scale":     list(scale)},
            "locked": locked or set(),
        }

    # ---- cmds stub --------------------------------------------------------
    def build_cmds_mock(self) -> MagicMock:
        scene = self

        m = MagicMock()

        def ls(*args, **kwargs):
            if kwargs.get("type") == "nurbsCurve":
                return [t["shape"] for t in scene.transforms.values()]
            if args:
                name = args[0]
                hits = [lp for lp, t in scene.transforms.items()
                        if t["short"] == name]
                return hits
            return []

        def listRelatives(node, **kwargs):
            if kwargs.get("parent"):
                for lp, t in scene.transforms.items():
                    if node == t["shape"]:
                        return [lp]
                return []
            if kwargs.get("shapes"):
                t = scene.transforms.get(node)
                return [t["shape"]] if t else []
            return []

        def getAttr(attr, **kwargs):
            # Locked queries.
            if kwargs.get("lock"):
                node, _, channel = attr.partition(".")
                t = scene.transforms.get(node)
                return bool(t and channel in t["locked"])

            # intermediateObject probe — never intermediate in our fake.
            if attr.endswith(".intermediateObject"):
                return False

            node, _, channel = attr.partition(".")

            # TRS reads — getAttr on .translate / .rotate / .scale returns
            # [(x, y, z)] in real Maya.
            if channel in ("translate", "rotate", "scale"):
                t = scene.transforms.get(node)
                if t:
                    return [tuple(t["trs"][channel])]
                # Maybe queried on a shape's parent transform via path.
                for lp, td in scene.transforms.items():
                    if lp == node:
                        return [tuple(td["trs"][channel])]
                return [(0.0, 0.0, 0.0)]

            # Colour override probes — these run against the shape.
            for lp, t in scene.transforms.items():
                if attr.startswith(t["shape"]):
                    suffix = attr.split(".", 1)[1]
                    color = t["color"]
                    if suffix == "overrideEnabled":
                        return bool(color)
                    if color is None:
                        return 0
                    return color.get(suffix, 0)

            return scene.attr_values.get(attr, 0)

        def setAttr(attr, *value, **kwargs):
            node, _, channel = attr.partition(".")
            t = scene.transforms.get(node)
            if t:
                if channel in ("translateX", "translateY", "translateZ"):
                    idx = "XYZ".index(channel[-1])
                    t["trs"]["translate"][idx] = float(value[0])
                    return
                if channel in ("rotateX", "rotateY", "rotateZ"):
                    idx = "XYZ".index(channel[-1])
                    t["trs"]["rotate"][idx] = float(value[0])
                    return
                if channel in ("scaleX", "scaleY", "scaleZ"):
                    idx = "XYZ".index(channel[-1])
                    t["trs"]["scale"][idx] = float(value[0])
                    return
            # Colour override writes — store on the relevant transform's color.
            for lp, td in scene.transforms.items():
                if attr.startswith(td["shape"]):
                    suffix = attr.split(".", 1)[1]
                    if td["color"] is None:
                        td["color"] = {}
                    td["color"][suffix] = value[0]
                    return
            scene.attr_values[attr] = value[0] if len(value) == 1 else value

        m.ls.side_effect = ls
        m.listRelatives.side_effect = listRelatives
        m.getAttr.side_effect = getAttr
        m.setAttr.side_effect = setAttr
        m.curve.side_effect = lambda **kw: "tempCurve#"
        m.delete.return_value = None
        m.parent.return_value = None
        m.undoInfo.return_value = None
        m.file.return_value = "untitled.ma"
        return m


# ---------------------------------------------------------------------------
# get_all_shapes_data stub — keeps tests independent of Control internals
# ---------------------------------------------------------------------------

def _stub_control_class():
    """Patch ``Control.get_all_shapes_data`` to return a deterministic shape."""
    fake_shape = {
        "cv_positions": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        "degree": 1,
        "knots": [0, 1, 2],
        "form": 0,
    }
    inst = MagicMock()
    inst.get_all_shapes_data.return_value = [fake_shape]
    return MagicMock(return_value=inst), fake_shape


# ---------------------------------------------------------------------------
# 1. save_scene_snapshot — writes valid JSON with expected payload
# ---------------------------------------------------------------------------

def test_save_scene_snapshot_writes_payload(tmp_path):
    from app.core import scene_snapshot

    scene = FakeScene()
    scene.add_control(
        "arm_L_CTRL",
        translate=(1.0, 2.0, 3.0),
        color={"overrideEnabled": True, "overrideRGBColors": True,
               "overrideColor": 0, "overrideColorR": 1.0,
               "overrideColorG": 0.0, "overrideColorB": 0.0},
    )
    scene.add_control("hip_CTRL")

    cmds_mock = scene.build_cmds_mock()
    ControlMock, fake_shape = _stub_control_class()

    dest = tmp_path / "snap.json"
    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch.object(scene_snapshot, "Control", ControlMock):
        result = scene_snapshot.save_scene_snapshot(str(dest))

    assert result.count == 2
    assert set(result.saved) == {"arm_L_CTRL", "hip_CTRL"}

    payload = json.loads(dest.read_text())
    assert payload["format"] == scene_snapshot.SNAPSHOT_FORMAT
    assert payload["version"] == scene_snapshot.SNAPSHOT_VERSION
    names = [c["name"] for c in payload["controls"]]
    assert set(names) == {"arm_L_CTRL", "hip_CTRL"}

    arm = next(c for c in payload["controls"] if c["name"] == "arm_L_CTRL")
    assert "transform" not in arm  # TRS is intentionally not captured
    assert arm["color"]["overrideColorR"] == 1.0
    assert arm["shapes"][0]["degree"] == 1


# ---------------------------------------------------------------------------
# 2. round-trip — save then load, all controls report replaced
# ---------------------------------------------------------------------------

def test_save_load_round_trip(tmp_path):
    from app.core import scene_snapshot

    scene = FakeScene()
    scene.add_control("arm_L_CTRL",
                      color={"overrideEnabled": True, "overrideRGBColors": True,
                             "overrideColor": 0, "overrideColorR": 1.0,
                             "overrideColorG": 0.0, "overrideColorB": 0.0})
    scene.add_control("hip_CTRL")

    cmds_mock = scene.build_cmds_mock()
    ControlMock, _ = _stub_control_class()

    dest = tmp_path / "snap.json"
    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch.object(scene_snapshot, "Control", ControlMock), \
         patch("app.core.operations.cmds", cmds_mock), \
         patch("app.compat.is_maya", return_value=False):
        scene_snapshot.save_scene_snapshot(str(dest))

        # Mutate pose AND colour so we can verify only colour comes back.
        scene.transforms["|arm_L_CTRL"]["trs"]["translate"] = [99.0, 99.0, 99.0]
        scene.transforms["|arm_L_CTRL"]["color"] = None

        result = scene_snapshot.load_scene_snapshot(str(dest))

    assert set(result.replaced) == {"arm_L_CTRL", "hip_CTRL"}
    assert result.missing == []
    assert result.ambiguous == []
    # Pose is NOT restored — TRS edits in the scene are preserved.
    assert scene.transforms["|arm_L_CTRL"]["trs"]["translate"] == [99.0, 99.0, 99.0]
    # Colour IS restored.
    assert scene.transforms["|arm_L_CTRL"]["color"]["overrideColorR"] == 1.0


# ---------------------------------------------------------------------------
# 3. missing match — snapshot references a name not in the scene
# ---------------------------------------------------------------------------

def test_load_reports_missing(tmp_path):
    from app.core import scene_snapshot

    payload = {
        "format":  scene_snapshot.SNAPSHOT_FORMAT,
        "version": scene_snapshot.SNAPSHOT_VERSION,
        "controls": [{
            "name": "ghost_CTRL",
            "shapes": [{"cv_positions": [(0, 0, 0), (1, 0, 0)],
                        "degree": 1, "knots": [0, 1], "form": 0}],
            "color": None,
        }],
    }
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(payload))

    scene = FakeScene()
    scene.add_control("arm_L_CTRL")
    cmds_mock = scene.build_cmds_mock()

    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch("app.core.operations.cmds", cmds_mock), \
         patch("app.compat.is_maya", return_value=False):
        result = scene_snapshot.load_scene_snapshot(str(path))

    assert result.missing == ["ghost_CTRL"]
    assert result.replaced == []


# ---------------------------------------------------------------------------
# 4. ambiguous — two scene transforms share the snapshot's short name
# ---------------------------------------------------------------------------

def test_load_reports_ambiguous(tmp_path):
    from app.core import scene_snapshot

    payload = {
        "format":  scene_snapshot.SNAPSHOT_FORMAT,
        "version": scene_snapshot.SNAPSHOT_VERSION,
        "controls": [{
            "name": "arm_L_CTRL",
            "shapes": [{"cv_positions": [(0, 0, 0), (1, 0, 0)],
                        "degree": 1, "knots": [0, 1], "form": 0}],
            "color": None,
        }],
    }
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(payload))

    # Two transforms with the same short name (different groups).
    scene = FakeScene()
    scene.transforms["|grpA|arm_L_CTRL"] = {
        "short": "arm_L_CTRL", "shape": "|grpA|arm_L_CTRL|s",
        "color": None,
        "trs":   {"translate": [0, 0, 0], "rotate": [0, 0, 0], "scale": [1, 1, 1]},
        "locked": set(),
    }
    scene.transforms["|grpB|arm_L_CTRL"] = {
        "short": "arm_L_CTRL", "shape": "|grpB|arm_L_CTRL|s",
        "color": None,
        "trs":   {"translate": [0, 0, 0], "rotate": [0, 0, 0], "scale": [1, 1, 1]},
        "locked": set(),
    }
    cmds_mock = scene.build_cmds_mock()

    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch("app.core.operations.cmds", cmds_mock), \
         patch("app.compat.is_maya", return_value=False):
        result = scene_snapshot.load_scene_snapshot(str(path))

    assert result.ambiguous == ["arm_L_CTRL"]
    assert result.replaced == []


# ---------------------------------------------------------------------------
# 5. bad format / version — raises ValueError
# ---------------------------------------------------------------------------

def test_load_rejects_unknown_format(tmp_path):
    from app.core import scene_snapshot

    path = tmp_path / "snap.json"
    path.write_text(json.dumps({"format": "something_else", "version": 1}))

    with pytest.raises(ValueError):
        scene_snapshot.load_scene_snapshot(str(path))


def test_load_rejects_unsupported_version(tmp_path):
    from app.core import scene_snapshot

    path = tmp_path / "snap.json"
    path.write_text(json.dumps({
        "format":   scene_snapshot.SNAPSHOT_FORMAT,
        "version":  999,
        "controls": [],
    }))

    with pytest.raises(ValueError):
        scene_snapshot.load_scene_snapshot(str(path))


# ---------------------------------------------------------------------------
# 6. merge save — second save replaces matching entries and appends new ones
# ---------------------------------------------------------------------------

def test_save_merges_into_existing_snapshot(tmp_path):
    from app.core import scene_snapshot

    # Pre-existing snapshot with an entry NOT in the scene (preserved) and
    # one entry that will be replaced by the upcoming save.
    pre = {
        "format":   scene_snapshot.SNAPSHOT_FORMAT,
        "version":  scene_snapshot.SNAPSHOT_VERSION,
        "saved_at": "2020-01-01T00:00:00",
        "controls": [
            {"name": "old_only_CTRL",
             "shapes": [{"cv_positions": [(9, 9, 9)], "degree": 1,
                         "knots": [0], "form": 0}],
             "color": None},
            {"name": "arm_L_CTRL",
             "shapes": [{"cv_positions": [(0, 0, 0)], "degree": 1,
                         "knots": [0], "form": 0}],
             "color": None},
        ],
    }
    dest = tmp_path / "snap.json"
    dest.write_text(json.dumps(pre))

    # Scene has arm_L_CTRL (will replace) and hip_CTRL (will append).
    scene = FakeScene()
    scene.add_control("arm_L_CTRL")
    scene.add_control("hip_CTRL")

    cmds_mock = scene.build_cmds_mock()
    ControlMock, fake_shape = _stub_control_class()

    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch.object(scene_snapshot, "Control", ControlMock):
        result = scene_snapshot.save_scene_snapshot(str(dest))

    assert result.replaced == ["arm_L_CTRL"]
    assert result.added == ["hip_CTRL"]

    payload = json.loads(dest.read_text())
    names = [c["name"] for c in payload["controls"]]
    # old_only_CTRL is preserved at its original index 0.
    assert names == ["old_only_CTRL", "arm_L_CTRL", "hip_CTRL"]
    # arm_L_CTRL's shapes were replaced with fresh data (3 CVs, not 1).
    arm = next(c for c in payload["controls"] if c["name"] == "arm_L_CTRL")
    assert len(arm["shapes"][0]["cv_positions"]) == 3


def test_save_rejects_non_snapshot_file(tmp_path):
    from app.core import scene_snapshot

    dest = tmp_path / "snap.json"
    dest.write_text(json.dumps({"format": "something_else", "version": 1}))

    scene = FakeScene()
    scene.add_control("arm_L_CTRL")
    cmds_mock = scene.build_cmds_mock()
    ControlMock, _ = _stub_control_class()

    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch.object(scene_snapshot, "Control", ControlMock):
        with pytest.raises(ValueError):
            scene_snapshot.save_scene_snapshot(str(dest))

    # File must not have been overwritten.
    assert json.loads(dest.read_text())["format"] == "something_else"


def test_save_empty_scene_leaves_file_untouched(tmp_path):
    from app.core import scene_snapshot

    dest = tmp_path / "snap.json"
    pre = {
        "format":   scene_snapshot.SNAPSHOT_FORMAT,
        "version":  scene_snapshot.SNAPSHOT_VERSION,
        "saved_at": "2020-01-01T00:00:00",
        "controls": [{"name": "old_CTRL",
                      "shapes": [{"cv_positions": [(0, 0, 0)], "degree": 1,
                                  "knots": [0], "form": 0}],
                      "color": None}],
    }
    dest.write_text(json.dumps(pre))

    scene = FakeScene()  # empty
    cmds_mock = scene.build_cmds_mock()
    ControlMock, _ = _stub_control_class()

    with patch.object(scene_snapshot, "cmds", cmds_mock), \
         patch.object(scene_snapshot, "Control", ControlMock):
        result = scene_snapshot.save_scene_snapshot(str(dest))

    assert result.saved == []
    # saved_at unchanged → file truly untouched.
    assert json.loads(dest.read_text())["saved_at"] == "2020-01-01T00:00:00"
