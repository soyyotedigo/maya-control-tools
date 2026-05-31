"""
Scene Controls Snapshot — save every NURBS-curve control in the current
Maya scene to a JSON file, then later load that file and *restore* the
matching scene controls (shape + override color + local TRS).

Why this module
---------------
``app.core.operations.replace_control`` is great for **library** shape
swaps: it normalises size, re-centers, and rotates to match the old flat
axis. That is the wrong behaviour for a snapshot restore — we want the
control to come back **exactly** the way it was saved, no size matching.

So this module does a direct curve rebuild from the saved CVs + degree +
knots + form, then reapplies the captured override colour. Matching is
by exact transform short name. Transform TRS is **not** restored — the
goal is to overlay shape/colour edits on top of whatever scene state the
rig file already has, never to disturb pose or hierarchy.

Two entry points
----------------
- ``save_scene_snapshot(path)`` → ``SaveResult``
- ``load_scene_snapshot(path)`` → ``LoadResult``

Both run quietly when Maya is not available so the module is safe to
import from tests; the actual Maya calls happen inside the functions
where ``cmds`` is a module-level reference (patchable in tests).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass, field

import maya.cmds as cmds

from app.core.control import Control
from app.core.operations import undo_chunk
from app.logger import log


SNAPSHOT_FORMAT = "controlme_scene_snapshot"
SNAPSHOT_VERSION = 1


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SaveResult:
    path: str
    saved: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.saved)


@dataclass
class LoadResult:
    path: str
    replaced: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers — colour capture / apply
# ---------------------------------------------------------------------------

def _read_override_color(transform: str) -> dict | None:
    """Capture every override-colour attr on the first nurbsCurve shape.

    Returns ``None`` when the shape has no override enabled, so unset
    controls round-trip as unset (instead of being forced to black).
    """
    shapes = cmds.listRelatives(transform, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    if not shapes:
        return None
    sh0 = shapes[0]
    try:
        if not cmds.getAttr(f"{sh0}.overrideEnabled"):
            return None
        return {
            "overrideEnabled":   True,
            "overrideRGBColors": bool(cmds.getAttr(f"{sh0}.overrideRGBColors")),
            "overrideColor":     int(cmds.getAttr(f"{sh0}.overrideColor")),
            "overrideColorR":    float(cmds.getAttr(f"{sh0}.overrideColorR")),
            "overrideColorG":    float(cmds.getAttr(f"{sh0}.overrideColorG")),
            "overrideColorB":    float(cmds.getAttr(f"{sh0}.overrideColorB")),
        }
    except Exception:
        return None


def _apply_override_color(transform: str, color: dict | None) -> None:
    if not color:
        return
    for sh in (cmds.listRelatives(transform, shapes=True, type="nurbsCurve",
                                  fullPath=True) or []):
        for attr, value in color.items():
            try:
                cmds.setAttr(f"{sh}.{attr}", value)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helpers — direct shape rebuild (no size normalisation)
# ---------------------------------------------------------------------------

def _apply_shapes_data(transform: str, shapes_data: list[dict]) -> None:
    """Restore the curve shapes under ``transform`` *exactly* as saved.

    Different from ``operations.replace_control``: no scale match, no
    flat-axis rotate, no re-center. Snapshots restore literally.

    When the existing topology matches what was saved (same shape count,
    same per-shape CV count + degree + form), CV positions are updated
    **in place** via ``cmds.xform`` — preserving every downstream
    connection (curveInfo, motionPath, deformers, etc.). Otherwise falls
    back to a destructive rebuild and warns, since incoming connections
    can't be carried across a topology change.
    """
    if not shapes_data:
        return

    existing = _existing_curve_shapes(transform)

    if _topology_matches(existing, shapes_data):
        for shape, s in zip(existing, shapes_data):
            _set_cv_positions(shape, s.get("cv_positions", []))
        return

    # Topology differs — must rebuild. Warn because connections will break.
    if existing:
        log.warning(
            "snapshot: topology of %s changed since save — rebuilding shapes "
            "(any incoming connections to the old shape nodes will be lost)",
            transform,
        )

    temp_nodes: list[str] = []
    for s in shapes_data:
        pts = [list(p) for p in s.get("cv_positions", [])]
        if not pts:
            continue
        degree = int(s.get("degree", 1))
        form = int(s.get("form", 0))
        knots = s.get("knots")

        kwargs: dict = {"degree": degree, "point": pts}
        if knots and len(knots) == len(pts) + degree - 1:
            kwargs["knot"] = knots
        if form == 2:
            kwargs["periodic"] = True

        temp_nodes.append(cmds.curve(**kwargs))

    if not temp_nodes:
        return

    old_shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    if old_shapes:
        cmds.delete(old_shapes)

    for tnode in temp_nodes:
        for sh in (cmds.listRelatives(tnode, shapes=True, fullPath=True) or []):
            cmds.parent(sh, transform, relative=True, shape=True)
        cmds.delete(tnode)


def _curve_cv_count(shape: str) -> int:
    """CV count read the *same way the snapshot was saved*.

    ``MFnNurbsCurve.cvPositions`` (used by ``Control.get_all_shapes_data``)
    returns ``spans + degree`` CVs for a periodic curve, while
    ``cmds.ls("shape.cv[*]")`` only reports the ``spans`` unique CVs. Counting
    via the API here keeps the topology check from falsely flagging every
    periodic (circle-based) control as changed.
    """
    try:
        from maya.api import OpenMaya as om
        sel = om.MSelectionList()
        sel.add(shape)
        fn = om.MFnNurbsCurve(sel.getDagPath(0))
        n = fn.numCVs
        if not isinstance(n, int):
            raise TypeError("OM2 not available in this context")
        return n
    except Exception:
        return len(cmds.ls(f"{shape}.cv[*]", flatten=True) or [])


def _set_cv_positions(shape: str, pts) -> None:
    """Move every CV in place — connection-preserving, periodic-safe.

    Uses ``MFnNurbsCurve.setCVPositions`` so the full CV array (including the
    wrapped CVs of a periodic curve) is written in one bulk call. Falls back to
    per-CV ``cmds.xform`` in standalone/mock mode.
    """
    pts = list(pts)
    if not pts:
        return
    try:
        from maya.api import OpenMaya as om
        sel = om.MSelectionList()
        sel.add(shape)
        fn = om.MFnNurbsCurve(sel.getDagPath(0))
        arr = om.MPointArray([om.MPoint(*p) for p in pts])
        fn.setCVPositions(arr, om.MSpace.kObject)
        fn.updateCurve()
        return
    except Exception:
        for i, pt in enumerate(pts):
            try:
                cmds.xform(f"{shape}.cv[{i}]",
                           objectSpace=True, translation=list(pt))
            except Exception:
                log.exception("snapshot: failed to set CV %d on %s", i, shape)


def _existing_curve_shapes(transform: str) -> list[str]:
    """Non-intermediate nurbsCurve shapes under ``transform``."""
    shapes = cmds.listRelatives(transform, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    keep: list[str] = []
    for sh in shapes:
        try:
            if cmds.getAttr(f"{sh}.intermediateObject"):
                continue
        except Exception:
            pass
        keep.append(sh)
    return keep


def _topology_matches(existing_shapes: list[str], shapes_data: list[dict]) -> bool:
    """True iff in-place CV updates are safe (same shape/CV/degree/form)."""
    if len(existing_shapes) != len(shapes_data):
        return False
    for shape, s in zip(existing_shapes, shapes_data):
        saved_pts = s.get("cv_positions", []) or []
        try:
            cv_count = _curve_cv_count(shape)
            cur_degree = int(cmds.getAttr(f"{shape}.degree"))
            cur_form = int(cmds.getAttr(f"{shape}.form"))
        except Exception:
            return False
        if cv_count != len(saved_pts):
            return False
        if cur_degree != int(s.get("degree", cur_degree)):
            return False
        if cur_form != int(s.get("form", cur_form)):
            return False
    return True


# ---------------------------------------------------------------------------
# Scene scanning
# ---------------------------------------------------------------------------

def _iter_curve_transforms() -> list[str]:
    """Return long-path transform names that own at least one nurbsCurve.

    Deduped — a transform with multiple curve shapes appears once.
    """
    curves = cmds.ls(type="nurbsCurve", long=True) or []
    seen: dict[str, None] = {}
    for sh in curves:
        # Skip intermediate / history shapes.
        try:
            if cmds.getAttr(f"{sh}.intermediateObject"):
                continue
        except Exception:
            pass
        parents = cmds.listRelatives(sh, parent=True, fullPath=True) or []
        if parents:
            seen.setdefault(parents[0], None)
    return list(seen.keys())


def _short_name(long_path: str) -> str:
    return long_path.rpartition("|")[2]


# ---------------------------------------------------------------------------
# Public — save
# ---------------------------------------------------------------------------

def save_scene_snapshot(path: str) -> SaveResult:
    """Merge current scene controls into a JSON snapshot at ``path``.

    Each save reads any existing snapshot, then for every curve control in
    the scene either **replaces** the matching entry (by short name) or
    **appends** a new one. Entries already in the JSON whose controls are
    no longer in the scene are preserved untouched — the file accumulates.
    """
    existing_controls, existing_index = _read_existing_snapshot(path)

    # Build fresh entries from the scene.
    fresh_by_name: dict[str, dict] = {}
    fresh_order: list[str] = []
    for transform_long in _iter_curve_transforms():
        short = _short_name(transform_long)
        try:
            shapes_data = Control(transform_long).get_all_shapes_data(space="object")
        except Exception:
            log.exception("snapshot: failed to read shapes on %s", transform_long)
            continue
        if not shapes_data:
            continue

        if short not in fresh_by_name:
            fresh_order.append(short)
        fresh_by_name[short] = {
            "name":   short,
            "shapes": shapes_data,
            "color":  _read_override_color(transform_long),
        }

    # Nothing in the scene: leave the file untouched.
    if not fresh_by_name:
        log.info("scene snapshot: no curve controls in scene, file untouched: %s", path)
        return SaveResult(path=path)

    # Merge: replace in place when name exists, otherwise append.
    merged: list[dict] = list(existing_controls)
    replaced: list[str] = []
    added: list[str] = []
    for short in fresh_order:
        entry = fresh_by_name[short]
        if short in existing_index:
            merged[existing_index[short]] = entry
            replaced.append(short)
        else:
            merged.append(entry)
            added.append(short)

    scene_file = ""
    try:
        scene_file = cmds.file(q=True, sceneName=True) or ""
    except Exception:
        pass

    payload = {
        "format":     SNAPSHOT_FORMAT,
        "version":    SNAPSHOT_VERSION,
        "saved_at":   _dt.datetime.now().isoformat(timespec="seconds"),
        "maya_scene": scene_file,
        "controls":   merged,
    }

    _write_json_atomic(path, payload)
    saved_names = replaced + added
    log.info(
        "scene snapshot saved: %d replaced, %d added → %s",
        len(replaced), len(added), path,
    )
    return SaveResult(
        path=path, saved=saved_names, replaced=replaced, added=added,
    )


def _read_existing_snapshot(path: str) -> tuple[list[dict], dict[str, int]]:
    """Load existing snapshot entries and a name→index map.

    Returns empty results when the file does not exist. Raises if the file
    is present but unreadable or has the wrong format/version — refusing to
    silently overwrite data the user can't recover.
    """
    if not os.path.exists(path):
        return [], {}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Existing snapshot at {path} is unreadable ({exc}). "
            "Refusing to overwrite — move or fix the file and retry."
        ) from exc

    fmt = payload.get("format")
    version = payload.get("version")
    if fmt != SNAPSHOT_FORMAT:
        raise ValueError(
            f"Existing file at {path} is not a snapshot (format={fmt!r}). "
            "Refusing to overwrite."
        )
    if version != SNAPSHOT_VERSION:
        raise ValueError(
            f"Existing snapshot at {path} has unsupported version {version!r}. "
            "Refusing to overwrite."
        )

    controls = payload.get("controls") or []
    index: dict[str, int] = {}
    for i, entry in enumerate(controls):
        name = entry.get("name")
        if name and name not in index:
            index[name] = i
    return list(controls), index


def _write_json_atomic(path: str, payload: dict) -> None:
    """Write to a sibling temp file then rename — avoids half-written JSON."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".snapshot_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public — load
# ---------------------------------------------------------------------------

def load_scene_snapshot(path: str) -> LoadResult:
    """Read a snapshot JSON and replace matching scene controls in-place."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    fmt = payload.get("format")
    version = payload.get("version")
    if fmt != SNAPSHOT_FORMAT:
        raise ValueError(f"Unknown snapshot format: {fmt!r}")
    if version != SNAPSHOT_VERSION:
        raise ValueError(f"Unsupported snapshot version: {version!r}")

    result = LoadResult(path=path)

    with undo_chunk("Load Scene Controls"):
        for entry in payload.get("controls", []):
            name = entry.get("name")
            if not name:
                continue

            matches = cmds.ls(name, long=True) or []
            if not matches:
                result.missing.append(name)
                continue
            if len(matches) > 1:
                result.ambiguous.append(name)
                continue
            target = matches[0]

            try:
                _apply_shapes_data(target, entry.get("shapes") or [])
                _apply_override_color(target, entry.get("color"))
            except Exception:
                log.exception("snapshot: failed to restore %s", name)
                continue

            result.replaced.append(name)

    log.info(
        "scene snapshot loaded: %d replaced, %d missing, %d ambiguous (path=%s)",
        len(result.replaced), len(result.missing), len(result.ambiguous), path,
    )
    return result
