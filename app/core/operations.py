"""
Maya control operations — heavy Maya logic extracted from views.

All public functions here require an active Maya session. They are
imported lazily (inside Maya-guarded method bodies) so this module
never loads during standalone execution.

Responsibilities:
  - Undo chunk context manager (single Ctrl+Z per operation).
  - Edge-to-curve helpers (connectivity grouping).
  - High-level control creation and shape replacement.
"""
from __future__ import annotations

import contextlib
from collections import defaultdict
from typing import Dict, Generator, List, Tuple

import maya.cmds as cmds

from app.core import om2_utils
from app.core.control import Control
from app.logger import log


# ---------------------------------------------------------------------------
# 1. Undo / Redo
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def undo_chunk(name: str) -> Generator[None, None, None]:
    """Wrap Maya commands so the entire operation is undone in one Ctrl+Z.

    Usage::

        with undo_chunk("Create Control"):
            cmds.curve(...)
            cmds.parent(...)

    Safe to call in a non-Maya environment (becomes a no-op there).
    """
    from app.compat import is_maya
    if is_maya():
        cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        if is_maya():
            cmds.undoInfo(closeChunk=True)


# ---------------------------------------------------------------------------
# 2. Edge connectivity helpers
# ---------------------------------------------------------------------------

def group_connected_edges(edges: list[str]) -> list[list[str]]:
    """Split a flat edge list into connected-component groups.

    Uses cmds.polyInfo to get vertex pairs, then union-find to cluster
    edges that share vertices.

    Args:
        edges: List of Maya edge component strings (e.g. ``"pCube1.e[0]"``).

    Returns:
        List of groups; each group is a list of edge component strings.
    """
    edge_verts: dict[str, tuple[int, int]] = {}

    # Try OM2 first (fast path in Maya).  On the first failure fall back to a
    # single batch cmds.polyInfo call so the mock in tests works correctly.
    om2_ok = True
    for edge in edges:
        mesh, idx_str = edge.split(".e[")
        idx = int(idx_str.rstrip("]"))
        try:
            v0, v1 = om2_utils.get_mesh_edge_vertices(mesh, idx)
            if not (isinstance(v0, int) and isinstance(v1, int)):
                raise TypeError("OM2 not available")
            edge_verts[edge] = (v0, v1)
        except Exception:
            om2_ok = False
            break

    if not om2_ok:
        # Fallback: single batch call; result order matches input edge order.
        edge_verts = {}
        info_list = cmds.polyInfo(edges, edgeToVertex=True) or []
        for edge, info in zip(edges, info_list):
            parts = info.split(":")[-1].split()
            edge_verts[edge] = (int(parts[0]), int(parts[1]))

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for v1, v2 in edge_verts.values():
        union(v1, v2)

    groups: dict[int, list[str]] = {}
    for edge, (v1, _) in edge_verts.items():
        groups.setdefault(find(v1), []).append(edge)

    return list(groups.values())


def group_has_branching(edges: list[str]) -> bool:
    """Return True if any vertex has more than 2 of the given edges meeting it.

    A branching vertex means the edges cannot form a single continuous,
    non-branching path — ``polyToCurve`` would silently drop edges.

    Args:
        edges: List of Maya edge component strings.
    """
    deg: dict[int, int] = defaultdict(int)
    for edge in edges:
        mesh, idx_str = edge.split(".e[")
        idx = int(idx_str.rstrip("]"))
        try:
            v1, v2 = om2_utils.get_mesh_edge_vertices(mesh, idx)
            if not (isinstance(v1, int) and isinstance(v2, int)):
                raise TypeError("OM2 not available")
        except Exception:
            info = cmds.polyInfo(edge, edgeToVertex=True)
            parts = info[0].split(":")[-1].split()
            v1, v2 = int(parts[0]), int(parts[1])
        deg[v1] += 1
        deg[v2] += 1
    return any(d > 2 for d in deg.values())


# ---------------------------------------------------------------------------
# 3. Control creation
# ---------------------------------------------------------------------------

def create_control_from_edges(edges: list[str]) -> tuple[Control, list[dict]]:
    """Convert a list of Maya edges to a NURBS curve control.

    Groups edges by connectivity, converts each group to a curve, and
    parents all shapes under one new transform node.  The pivot is
    centred after all shapes are collected.

    Args:
        edges: Expanded edge component strings (``filterExpand`` output).

    Returns:
        ``(control, shapes_data)`` where *control* wraps the new
        transform node and *shapes_data* is ready for ``db.save_custom_shape``.

    Raises:
        RuntimeError: If every edge group fails to convert.
    """
    groups = group_connected_edges(edges)
    transform = cmds.createNode("transform", name="ctrl_tmp")
    succeeded = 0

    for group in groups:
        if group_has_branching(group):
            # Branching topology (e.g. spheres, platonic solids) —
            # build one linear segment per edge to preserve the full shape.
            for edge in group:
                mesh, idx_str = edge.split(".e[")
                idx = int(idx_str.rstrip("]"))
                v1, v2 = om2_utils.get_mesh_edge_vertices(mesh, idx)
                p1 = om2_utils.get_vertex_world_position(mesh, v1)
                p2 = om2_utils.get_vertex_world_position(mesh, v2)
                crv = om2_utils.create_nurbs_curve([p1, p2], [0.0, 1.0], 1)
                cmds.delete(crv, constructionHistory=True)
                for sh in (cmds.listRelatives(crv, shapes=True) or []):
                    cmds.parent(sh, transform, relative=True, shape=True)
                cmds.delete(crv)
            succeeded += 1
            continue

        # Non-branching path — polyToCurve works cleanly.
        cmds.select(group)
        try:
            curve_node = cmds.polyToCurve(form=2, degree=1)[0]
        except Exception:
            try:
                curve_node = cmds.polyToCurve(form=0, degree=1)[0]
            except Exception:
                log.warning(
                    "create_control_from_edges: failed to convert group (first edge: %r)",
                    group[0] if group else "?",
                )
                continue

        cmds.delete(curve_node, constructionHistory=True)
        for sh in (cmds.listRelatives(curve_node, shapes=True) or []):
            cmds.parent(sh, transform, relative=True, shape=True)
        cmds.delete(curve_node)
        succeeded += 1

    if succeeded == 0:
        cmds.delete(transform)
        raise RuntimeError("Could not convert any edge group to a curve.")

    cmds.xform(transform, centerPivots=True)

    # Normalize flat shapes to XZ plane (Y-up).
    bb = cmds.exactWorldBoundingBox(transform)
    sx, sy, sz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    flat = _flat_axis(sx, sy, sz)
    if flat and flat != 'Y':
        rx, ry, rz = _ORIENT.get((flat, 'Y'), (0, 0, 0))
        if rx or ry or rz:
            cmds.rotate(rx, ry, rz, transform, objectSpace=True)
            cmds.makeIdentity(transform, apply=True, t=1, r=1, s=1, n=0)
            cmds.xform(transform, centerPivots=True)

    ctrl = Control(name=transform)
    shapes_data = ctrl.get_all_shapes_data()
    log.debug("create_control_from_edges: created %r with %d shape(s)", transform, len(shapes_data))
    return ctrl, shapes_data


def create_control_from_curves(transforms: list[str]) -> tuple[Control | None, list[dict]]:
    """Capture shapes_data from existing NURBS curve transforms.

    Args:
        transforms: List of Maya transform node names containing NURBS curves.

    Returns:
        ``(control, shapes_data)`` where *control* wraps the first
        transform and *shapes_data* combines all shapes from every node.
    """
    shapes_data: list[dict] = []
    first_ctrl: Control | None = None
    for t in transforms:
        ctrl = Control(name=t)
        if first_ctrl is None:
            first_ctrl = ctrl
        shapes_data.extend(ctrl.get_all_shapes_data())
    log.debug(
        "create_control_from_curves: captured %d shape(s) from %d transform(s)",
        len(shapes_data), len(transforms),
    )
    return first_ctrl, shapes_data


# ---------------------------------------------------------------------------
# 4. Shape replacement
# ---------------------------------------------------------------------------

# Rotation lookup: (from_flat_axis, to_flat_axis) → (rx, ry, rz).
_ORIENT: dict[tuple[str, str], tuple[int, int, int]] = {
    ('Z', 'Y'): (-90,  0,   0),   # XY  → XZ
    ('Z', 'X'): (  0, 90,   0),   # XY  → YZ
    ('Y', 'Z'): ( 90,  0,   0),   # XZ  → XY
    ('Y', 'X'): (  0,  0, -90),   # XZ  → YZ
    ('X', 'Z'): (  0, -90,  0),   # YZ  → XY
    ('X', 'Y'): (  0,  0,  90),   # YZ  → XZ
}


def _flat_axis(sx: float, sy: float, sz: float) -> str | None:
    """Return the axis letter with the least spread, or None when the shape is 3D.

    A shape is considered flat when its thinnest axis is < 15 % of the
    largest axis.
    """
    max_s = max(sx, sy, sz)
    if max_s == 0:
        return None
    pairs: list[tuple[str, float]] = [('X', sx), ('Y', sy), ('Z', sz)]
    axis, min_s = min(pairs, key=lambda p: p[1])
    return axis if (min_s / max_s) < 0.15 else None


def replace_control(
    node: str,
    shape: dict,
    replace_name: bool = False,
    replace_color: bool = True,
) -> str:
    """Swap the curve shape of a Maya control with a library shape.

    Preserves the existing object-space size, CV center offset, and
    guesses orientation from the flat axis of the old curve layout.

    Args:
        node:          Existing Maya transform node name.
        shape:         Shape dict from the database (as returned by ``db.get_shape``).
        replace_name:  When True, rename the transform to the library shape label.
        replace_color: When True (default), apply the library color to the new
                       shape. When False, re-apply whatever color override the
                       original control already had (preserving scene color).

    Returns:
        The final Maya transform node name (may differ from *node* when
        ``replace_name=True`` and the node was successfully renamed).
    """
    # ── 0. Capture existing color override so we can restore it after swap ──
    # Read ALL override attrs (not just RGB) so index-based colors (the
    # standard Maya integer palette) are preserved as well as RGB overrides.
    original_color_attrs: dict | None = None
    if not replace_color:
        pre_shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []
        if pre_shapes:
            sh0 = pre_shapes[0]
            try:
                if cmds.getAttr(f"{sh0}.overrideEnabled"):
                    original_color_attrs = {
                        "overrideEnabled":   True,
                        "overrideRGBColors": cmds.getAttr(f"{sh0}.overrideRGBColors"),
                        "overrideColor":     int(cmds.getAttr(f"{sh0}.overrideColor")),
                        "overrideColorR":    cmds.getAttr(f"{sh0}.overrideColorR"),
                        "overrideColorG":    cmds.getAttr(f"{sh0}.overrideColorG"),
                        "overrideColorB":    cmds.getAttr(f"{sh0}.overrideColorB"),
                    }
            except Exception:
                pass

    # ── 1. Analyse existing shape in object space ─────────────────────────
    # Use fullPath=True so the shape name is always unique, even when the
    # scene contains multiple nodes with the same short name.
    # openMaya fast path: bulk-read all CVs in one API call per shape.
    old_cv_pos: list[tuple[float, float, float]] = []
    old_shapes_full = cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []
    for sh in old_shapes_full:
        old_cv_pos.extend(om2_utils.get_nurbs_cv_positions(sh))

    if old_cv_pos:
        xs = [p[0] for p in old_cv_pos]
        ys = [p[1] for p in old_cv_pos]
        zs = [p[2] for p in old_cv_pos]
        sx = max(xs) - min(xs)
        sy = max(ys) - min(ys)
        sz = max(zs) - min(zs)
        old_obj_size: float = max(sx, sy, sz)
        old_center: tuple[float, float, float] = (
            (max(xs) + min(xs)) / 2.0,
            (max(ys) + min(ys)) / 2.0,
            (max(zs) + min(zs)) / 2.0,
        )
        old_axis = _flat_axis(sx, sy, sz)
    else:
        old_obj_size = 1.0
        old_center = (0.0, 0.0, 0.0)
        old_axis = None

    ctrl = Control(name=node)

    # ── 2. Build replacement: normalised, centred at world origin ─────────
    temp_node = Control.create_from_db(shape)
    temp_ctrl = Control(name=temp_node)
    temp_ctrl.normalize_scale()

    bb = cmds.exactWorldBoundingBox(temp_node)
    cx = (bb[0] + bb[3]) / 2.0
    cy = (bb[1] + bb[4]) / 2.0
    cz = (bb[2] + bb[5]) / 2.0
    for sh in (cmds.listRelatives(temp_node, shapes=True, fullPath=True) or []):
        cmds.move(-cx, -cy, -cz, f"{sh}.cv[*]", relative=True, worldSpace=True)
    cmds.xform(temp_node, centerPivots=True)

    # ── 3. Rotate new shape to match old flat axis ────────────────────────
    if old_axis:
        new_bb = cmds.exactWorldBoundingBox(temp_node)
        new_axis = _flat_axis(
            new_bb[3] - new_bb[0],
            new_bb[4] - new_bb[1],
            new_bb[5] - new_bb[2],
        )
        if new_axis and new_axis != old_axis:
            rx, ry, rz = _ORIENT.get((new_axis, old_axis), (0, 0, 0))
            if rx or ry or rz:
                cmds.rotate(rx, ry, rz, temp_node, objectSpace=True)
                cmds.makeIdentity(temp_node, apply=True, t=1, r=1, s=1, n=0)

    # ── 4. Scale to match old object-space size ───────────────────────────
    # Use CV spread (same method as old_obj_size) to avoid a systematic
    # mismatch: for cubic curves, CVs sit slightly outside the actual
    # geometry, so old_obj_size (CV spread) > exactWorldBoundingBox → factor
    # would be > 1 and the replacement would grow by ~2-3% each time.
    new_cv_pos: list[tuple[float, float, float]] = []
    for _sh in (cmds.listRelatives(temp_node, shapes=True, type="nurbsCurve", fullPath=True) or []):
        new_cv_pos.extend(om2_utils.get_nurbs_cv_positions(_sh))
    if new_cv_pos:
        nxs = [p[0] for p in new_cv_pos]
        nys = [p[1] for p in new_cv_pos]
        nzs = [p[2] for p in new_cv_pos]
        new_size = max(max(nxs) - min(nxs), max(nys) - min(nys), max(nzs) - min(nzs))
    else:
        new_size = temp_ctrl.get_max_dimension()
    if new_size > 0 and old_obj_size > 0:
        factor = old_obj_size / new_size
        cmds.scale(factor, factor, factor, temp_node)
        cmds.makeIdentity(temp_node, apply=True, t=1, r=1, s=1, n=0)

    # ── 5. Swap shapes ────────────────────────────────────────────────────
    old_shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
    if old_shapes:
        cmds.delete(old_shapes)
    for sh in (cmds.listRelatives(temp_node, shapes=True, fullPath=True) or []):
        cmds.parent(sh, node, relative=True, shape=True)
    cmds.delete(temp_node)

    # Restore old object-space center so the shape sits where the original was.
    ocx, ocy, ocz = old_center
    if abs(ocx) > 1e-4 or abs(ocy) > 1e-4 or abs(ocz) > 1e-4:
        for sh in (cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []):
            cmds.move(ocx, ocy, ocz, f"{sh}.cv[*]", relative=True, objectSpace=True)

    # Note: deliberately NOT calling cmds.xform(node, centerPivots=True) here.
    # The transform's pivot is a user-owned property — a shape swap must not
    # silently re-center it (this caused a regression where any pivot that
    # had been moved manually got snapped to the new shape's geometric center).

    # ── 6. Apply color ────────────────────────────────────────────────────
    from app.core.shape_data import decode_color
    if replace_color:
        color = decode_color(shape.get("color"))
        if color:
            ctrl.set_color(color)
    elif original_color_attrs:
        # Write every captured override attr directly so both RGB and
        # index-based colors are restored faithfully.
        for sh in (cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []):
            for attr, value in original_color_attrs.items():
                try:
                    cmds.setAttr(f"{sh}.{attr}", value)
                except Exception:
                    pass

    # ── 7. Optionally rename the transform to match the library label ─────
    if replace_name:
        raw = shape.get("label", "").strip().replace(" ", "_")
        if raw:
            node = cmds.rename(node, raw) or node

    log.debug("replace_control: replaced shape on %r", node)
    return node


# ---------------------------------------------------------------------------
# 5. CV orientation cycling
# ---------------------------------------------------------------------------

def rotate_control_cvs(node: str, axis: str, degrees: float = 90.0) -> None:
    """Rotate a control's curve CVs in its own object space.

    Moves only the CV points — the transform node, pivot, constraints, and
    connections are untouched.  Call repeatedly to cycle through orientations.

    Args:
        node:    Maya transform node name.
        axis:    Rotation axis: ``'x'``, ``'y'``, or ``'z'``.
        degrees: Amount to rotate (default 90°).
    """
    rx = degrees if axis == "x" else 0.0
    ry = degrees if axis == "y" else 0.0
    rz = degrees if axis == "z" else 0.0

    shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    if not shapes:
        log.warning("rotate_control_cvs: no nurbsCurve shapes on %r", node)
        return

    for sh in shapes:
        cvs = cmds.ls(f"{sh}.cv[*]", flatten=True) or []
        if cvs:
            cmds.rotate(rx, ry, rz, cvs, objectSpace=True, relative=True)

    log.debug("rotate_control_cvs: %r rotated %.0f° on %s", node, degrees, axis.upper())


def scale_control_cvs(node: str, factor: float, axes: str = "xyz",
                      from_center: bool = False) -> None:
    """Scale a control's curve CVs in its own object space.

    Like ``rotate_control_cvs``, this moves only the CV points — the
    transform's scale stays at 1,1,1 and pivot/connections are untouched.

    Args:
        node:   Maya transform node name.
        factor: Scale multiplier (1.0 = no change).
        axes:   Which object-space axes to scale, as a string containing any
                of ``'x'`` / ``'y'`` / ``'z'`` (default ``"xyz"`` = uniform).
                Axes not listed are left at 1.0.
        from_center: When False (default) the CVs scale about the transform
                pivot. When True they scale about the control's own centroid
                (mean of every CV across its shapes), so the shape grows or
                shrinks in place even if the pivot sits off-shape.
    """
    sx = factor if "x" in axes else 1.0
    sy = factor if "y" in axes else 1.0
    sz = factor if "z" in axes else 1.0

    shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    if not shapes:
        log.warning("scale_control_cvs: no nurbsCurve shapes on %r", node)
        return

    if from_center:
        _scale_cvs_about_centroid(shapes, (sx, sy, sz))
    else:
        for sh in shapes:
            cvs = cmds.ls(f"{sh}.cv[*]", flatten=True) or []
            if cvs:
                cmds.scale(sx, sy, sz, cvs, objectSpace=True, relative=True)

    log.debug("scale_control_cvs: %r scaled by %.4f on %s (center=%s)",
              node, factor, (axes or "none").upper(), from_center)


def _scale_cvs_about_centroid(shapes: list[str],
                              scale: tuple[float, float, float]) -> None:
    """Scale every CV of ``shapes`` about their shared object-space centroid.

    The centroid is the mean of all CV positions across the given shapes.
    Scaling about it keeps that point fixed, so a control resizes in place.
    """
    # First pass: read object-space CV positions and accumulate the centroid.
    shape_cvs: dict[str, list[str]] = {}
    positions: dict[str, list[tuple[float, float, float]]] = {}
    sums = [0.0, 0.0, 0.0]
    total = 0
    for sh in shapes:
        cvs = cmds.ls(f"{sh}.cv[*]", flatten=True) or []
        shape_cvs[sh] = cvs
        pl: list[tuple[float, float, float]] = []
        for cv in cvs:
            p = cmds.xform(cv, query=True, objectSpace=True, translation=True)
            pl.append((p[0], p[1], p[2]))
            sums[0] += p[0]
            sums[1] += p[1]
            sums[2] += p[2]
            total += 1
        positions[sh] = pl

    if total == 0:
        return
    center = (sums[0] / total, sums[1] / total, sums[2] / total)

    # Second pass: scale each CV about the centroid on the requested axes.
    for sh, cvs in shape_cvs.items():
        for cv, p in zip(cvs, positions[sh]):
            new = [c + (pv - c) * s for pv, c, s in zip(p, center, scale)]
            cmds.xform(cv, objectSpace=True, translation=new)


# ---------------------------------------------------------------------------
# 6. Batch / selection-driven use cases
# ---------------------------------------------------------------------------

def replace_controls_in_selection(
    shape: dict,
    replace_name: bool = False,
    replace_color: bool = True,
) -> int:
    """Swap the curve shape of every selected Maya transform with *shape*.

    Wraps all swaps in a single undo chunk so the entire batch is
    reversible with one Ctrl+Z.

    Args:
        shape:          Shape dict from the database (as returned by ``db.get_shape``).
        replace_name:   Rename each transform to the library shape label.
        replace_color:  Apply library color; when False, preserve scene color.

    Returns:
        The number of transforms that were replaced (``0`` when nothing
        was selected — caller can show a warning).
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0
    final_sel: list[str] = []
    with undo_chunk("Replace Control"):
        for node in sel:
            final_node = replace_control(
                node, shape,
                replace_name=replace_name,
                replace_color=replace_color,
            )
            final_sel.append(final_node)
        # Control.create_from_db auto-selects the temp node; deleting it
        # clears the selection. Restore so subsequent scale/rotate ops
        # operate on the new controls.
        cmds.select(final_sel)
    return len(sel)


def rotate_selected_cvs(axis: str, degrees: float) -> int:
    """Rotate the CVs of every selected Maya control by *degrees* on *axis*.

    Each call is its own undo chunk so Ctrl+Z undoes one step at a time.

    Args:
        axis:    Rotation axis: ``'x'``, ``'y'``, or ``'z'``.
        degrees: Signed rotation amount. Positive = +N°, negative = -N°.

    Returns:
        The number of transforms that were rotated (``0`` when nothing
        was selected).
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0
    direction = "+" if degrees > 0 else "-"
    with undo_chunk(f"Orient CV {direction}{axis.upper()}"):
        for node in sel:
            rotate_control_cvs(node, axis, degrees)
    return len(sel)


def scale_selected_cvs(factor: float, axes: str = "xyz",
                       from_center: bool = False) -> int:
    """Scale the CVs of every selected Maya control by *factor*.

    ``axes`` selects which object-space axes are scaled (default ``"xyz"`` =
    uniform); e.g. ``"xz"`` scales X and Z and leaves Y unchanged.
    ``from_center`` pivots each control on its own CV centroid instead of its
    transform pivot.

    Returns the number of transforms that were scaled (``0`` when nothing
    was selected, when *factor* is effectively 1.0, or when ``axes`` is
    empty). The whole operation is wrapped in a single undo chunk, so one
    call = one Ctrl+Z.
    """
    if abs(factor - 1.0) < 1e-6 or not axes:
        return 0
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0

    chunk = "Scale CV" if axes == "xyz" else f"Scale CV {axes.upper()}"
    with undo_chunk(chunk):
        for node in sel:
            scale_control_cvs(node, factor, axes=axes, from_center=from_center)
    return len(sel)


class ScaleDragSession:
    """Group an entire scale-drag gesture under one undo chunk.

    Usage::

        session = ScaleDragSession.start()  # captures selection, opens chunk
        if session:
            session.apply(1.05)             # called per slider tick
            ...
            session.end()                   # closes chunk

    ``start()`` returns ``None`` if nothing is selected, so callers can
    skip the chunk overhead in that case.
    """

    def __init__(self, nodes: list[str], axes: str = "xyz",
                 from_center: bool = False) -> None:
        self._nodes = nodes
        self._axes = axes
        self._from_center = from_center
        self._closed = False

    @classmethod
    def start(cls, axes: str = "xyz",
              from_center: bool = False) -> "ScaleDragSession | None":
        sel = cmds.ls(selection=True, transforms=True) or []
        if not sel:
            return None
        from app.compat import is_maya
        if is_maya():
            chunk = "Scale CV" if axes == "xyz" else f"Scale CV {axes.upper()}"
            cmds.undoInfo(openChunk=True, chunkName=chunk)
        return cls(sel, axes=axes, from_center=from_center)

    def apply(self, factor: float) -> None:
        if abs(factor - 1.0) < 1e-6 or not self._axes:
            return
        for node in self._nodes:
            scale_control_cvs(node, factor, axes=self._axes,
                              from_center=self._from_center)

    def end(self) -> None:
        if self._closed:
            return
        self._closed = True
        from app.compat import is_maya
        if is_maya():
            cmds.undoInfo(closeChunk=True)


# ---------------------------------------------------------------------------
# 7b. CV snapshot / reset
# ---------------------------------------------------------------------------

# A snapshot maps shape-name → list of (x, y, z) CV positions in object space.
# Uses typing aliases (not ``dict[...]``) so the module imports on Python 3.7
# (Maya 2022), where subscripting builtin generics at runtime is unsupported.
CvSnapshot = Dict[str, List[Tuple[float, float, float]]]


def snapshot_cv_positions(node: str) -> CvSnapshot:
    """Capture object-space CV positions for every nurbsCurve shape on ``node``.

    The result can be passed back to ``restore_cv_positions`` later to undo
    any number of subsequent CV-level edits (scale, rotate, etc.).
    """
    shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    snapshot: CvSnapshot = {}
    for sh in shapes:
        cvs = cmds.ls(f"{sh}.cv[*]", flatten=True) or []
        positions: list[tuple[float, float, float]] = []
        for cv in cvs:
            pos = cmds.xform(cv, query=True, objectSpace=True, translation=True)
            positions.append((pos[0], pos[1], pos[2]))
        snapshot[sh] = positions
    return snapshot


def restore_cv_positions(
    node: str, snapshot: CvSnapshot, axes: str = "xyz"
) -> None:
    """Restore CV positions previously captured by ``snapshot_cv_positions``.

    With ``axes`` ``"xyz"`` every CV is restored to its full snapshot
    position. Pass a subset (e.g. ``"x"`` or ``"xz"``) to restore only those
    object-space components, leaving the other axes at their current values —
    the counterpart to a gated scale.

    Silently skips shapes whose CV count no longer matches the snapshot
    (e.g. the curve was rebuilt), logging a warning instead of raising.
    """
    idxs = [i for i, a in enumerate("xyz") if a in axes]
    if not idxs:
        return
    full = (len(idxs) == 3)
    for sh, positions in snapshot.items():
        cvs = cmds.ls(f"{sh}.cv[*]", flatten=True) or []
        if len(cvs) != len(positions):
            log.warning(
                "restore_cv_positions: CV count mismatch on %r "
                "(snapshot=%d, current=%d) — skipping",
                sh, len(positions), len(cvs),
            )
            continue
        for cv, pos in zip(cvs, positions):
            if full:
                cmds.xform(cv, objectSpace=True, translation=pos)
            else:
                cur = cmds.xform(cv, query=True, objectSpace=True,
                                 translation=True)
                for i in idxs:
                    cur[i] = pos[i]
                cmds.xform(cv, objectSpace=True, translation=cur)


def ensure_snapshots_for_selection(snapshots: dict[str, CvSnapshot]) -> None:
    """For every selected transform, add an entry to ``snapshots`` if missing.

    Mutates ``snapshots`` in place. Use this before applying a scale/rotate
    so that a later reset can restore the original CV positions.

    Existing entries are validated: if the shape nodes on a transform have
    changed since the snapshot was taken (e.g. Replace Control was called),
    the stale entry is discarded and re-captured.
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    for node in sel:
        if node in snapshots:
            current_shapes = set(
                cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []
            )
            if set(snapshots[node].keys()) != current_shapes:
                del snapshots[node]
        if node not in snapshots:
            snapshots[node] = snapshot_cv_positions(node)


def reset_selected_cvs(
    snapshots: dict[str, CvSnapshot],
    axes: str = "xyz",
) -> int:
    """Restore CV positions of every selected transform that has a snapshot.

    ``axes`` ``"xyz"`` restores the full snapshot position; pass a subset
    (e.g. ``"x"`` or ``"xz"``) to restore only those object-space components.

    Returns the number of nodes restored (``0`` when no snapshot matches or
    ``axes`` is empty). Whole operation is one undo chunk. Nodes without an
    entry in ``snapshots`` are silently skipped.
    """
    if not axes:
        return 0
    sel = cmds.ls(selection=True, transforms=True) or []
    targets = [n for n in sel if n in snapshots]
    if not targets:
        return 0
    chunk = "Reset Scale" if axes == "xyz" else f"Reset Scale {axes.upper()}"
    with undo_chunk(chunk):
        for node in targets:
            restore_cv_positions(node, snapshots[node], axes=axes)
    return len(targets)


# ---------------------------------------------------------------------------
# 7c. Mirror
# ---------------------------------------------------------------------------

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}

# Side tokens recognised when locating a control's opposite-side counterpart.
# Order matters: more specific patterns (infix ``_L_``) are tested before the
# looser prefix/suffix ones. Each entry is (kind, left_token, right_token).
_SIDE_TOKENS = [
    ("infix", "_L_", "_R_"),
    ("infix", "_l_", "_r_"),
    ("prefix", "L_", "R_"),
    ("prefix", "l_", "r_"),
    ("suffix", "_L", "_R"),
    ("suffix", "_l", "_r"),
    ("infix", "Left", "Right"),
    ("infix", "left", "right"),
]


def mirror_name(name: str) -> str | None:
    """Return the opposite-side counterpart short name, or ``None``.

    Recognises L/R side tokens as infix (``arm_L_ctl``), prefix (``L_arm``),
    suffix (``arm_L``) and the words ``Left``/``Right`` (both cases). Any DAG
    path is stripped, so only the short name is compared and returned.
    """
    short = name.rpartition("|")[2]
    for kind, left, right in _SIDE_TOKENS:
        for a, b in ((left, right), (right, left)):
            if kind == "prefix" and short.startswith(a):
                return b + short[len(a):]
            if kind == "suffix" and short.endswith(a):
                return short[:-len(a)] + b
            if kind == "infix" and a in short:
                return short.replace(a, b, 1)
    return None


def _flip_cvs_in_place(node: str, axis: str) -> bool:
    """Mirror a control's own CVs across its local ``axis``. Connection-safe.

    Returns True when at least one curve shape was flipped.
    """
    idx = _AXIS_INDEX[axis]
    shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                fullPath=True) or []
    if not shapes:
        log.warning("mirror: no nurbsCurve shapes on %r", node)
        return False
    for sh in shapes:
        for cv in (cmds.ls(f"{sh}.cv[*]", flatten=True) or []):
            pos = cmds.xform(cv, query=True, objectSpace=True, translation=True)
            pos[idx] = -pos[idx]
            cmds.xform(cv, objectSpace=True, translation=pos)
    return True


def _read_mirrored_world(shapes: list[str], idx: int) -> list[list]:
    """Per shape, return its CVs' world positions with axis ``idx`` negated."""
    out: list[list] = []
    for sh in shapes:
        pts = []
        for cv in (cmds.ls(f"{sh}.cv[*]", flatten=True) or []):
            p = cmds.xform(cv, query=True, worldSpace=True, translation=True)
            p[idx] = -p[idx]
            pts.append(p)
        out.append(pts)
    return out


def _override_color_attrs(shape: str) -> dict | None:
    """Capture a shape's override-colour attrs, or None when not overridden."""
    try:
        if not cmds.getAttr(f"{shape}.overrideEnabled"):
            return None
        attrs = {
            "overrideEnabled":   True,
            "overrideRGBColors": cmds.getAttr(f"{shape}.overrideRGBColors"),
            "overrideColor":     cmds.getAttr(f"{shape}.overrideColor"),
        }
        for c in ("R", "G", "B"):
            attrs[f"overrideColor{c}"] = cmds.getAttr(f"{shape}.overrideColor{c}")
        return attrs
    except Exception:
        return None


def _apply_color_attrs(shapes: list[str], attrs: dict | None) -> None:
    if not attrs:
        return
    for sh in shapes:
        for attr, val in attrs.items():
            try:
                cmds.setAttr(f"{sh}.{attr}", val)
            except Exception:
                pass


def _mirror_onto(src: str, dst: str, axis: str) -> bool:
    """Mirror ``src``'s shape onto ``dst`` across the world ``axis`` plane.

    When the two controls share topology (same shape + CV count), CVs are
    updated in place so ``dst``'s connections are preserved. When the shapes
    differ, ``dst``'s curves are rebuilt as a mirrored copy of ``src`` (its
    override colour is kept) — incoming connections to the old shape nodes are
    lost, which is unavoidable when the shape itself changes. Returns False
    (caller counts it as *skipped*) only when ``src`` has no curve shapes.
    """
    idx = _AXIS_INDEX[axis]
    src_shapes = cmds.listRelatives(src, shapes=True, type="nurbsCurve",
                                    fullPath=True) or []
    if not src_shapes:
        return False
    src_world = _read_mirrored_world(src_shapes, idx)

    dst_shapes = cmds.listRelatives(dst, shapes=True, type="nurbsCurve",
                                    fullPath=True) or []
    dst_cv_lists = [cmds.ls(f"{d}.cv[*]", flatten=True) or [] for d in dst_shapes]

    topology_matches = (
        len(dst_shapes) == len(src_shapes)
        and all(len(d) == len(p) for d, p in zip(dst_cv_lists, src_world))
        and all(dst_cv_lists)
    )

    if topology_matches:
        # Connection-safe: move existing CVs to the mirrored world positions.
        for d_cvs, pts in zip(dst_cv_lists, src_world):
            for d_cv, p in zip(d_cvs, pts):
                cmds.xform(d_cv, worldSpace=True, translation=p)
        return True

    _rebuild_mirror(src, dst, src_world)
    return True


def _rebuild_mirror(src: str, dst: str, src_world: list[list]) -> None:
    """Replace ``dst``'s curve shapes with a mirrored copy of ``src``'s.

    Duplicates ``src`` (preserving exact degree/knots/form), transfers its
    curve shapes onto ``dst``, then moves every CV to its mirrored world
    position from ``src_world``. ``dst``'s override colour is reapplied.
    """
    old_shapes = cmds.listRelatives(dst, shapes=True, type="nurbsCurve",
                                    fullPath=True) or []
    color = _override_color_attrs(old_shapes[0]) if old_shapes else None

    dup = cmds.duplicate(src, returnRootsOnly=True)[0]
    # Drop any duplicated child transforms — we only want the curve shapes.
    for child in (cmds.listRelatives(dup, children=True, type="transform",
                                     fullPath=True) or []):
        cmds.delete(child)
    dup_shapes = [s for s in (cmds.listRelatives(dup, shapes=True,
                                                 type="nurbsCurve",
                                                 fullPath=True) or [])
                  if not cmds.getAttr(f"{s}.intermediateObject")]

    if old_shapes:
        cmds.delete(old_shapes)
    for sh in dup_shapes:
        cmds.parent(sh, dst, relative=True, shape=True)
    cmds.delete(dup)

    new_shapes = cmds.listRelatives(dst, shapes=True, type="nurbsCurve",
                                    fullPath=True) or []
    for d_sh, pts in zip(new_shapes, src_world):
        d_cvs = cmds.ls(f"{d_sh}.cv[*]", flatten=True) or []
        for d_cv, p in zip(d_cvs, pts):
            cmds.xform(d_cv, worldSpace=True, translation=p)

    _apply_color_attrs(new_shapes, color)


def mirror_selected_controls(axis: str = "x") -> tuple[int, int, int]:
    """Mirror every selected control across the world ``axis``.

    For each selected transform: if a name counterpart (L<->R) exists in the
    scene, mirror the shape onto that opposite control (updating CVs in place
    when topology matches, else rebuilding the opposite shape); otherwise flip
    the control's own CVs in place. Returns ``(mirrored, flipped, skipped)`` —
    skipped now only covers an ambiguous counterpart name (or a counterpart
    with no curve shapes). The whole batch is one undo chunk.
    """
    if axis not in _AXIS_INDEX:
        return (0, 0, 0)
    sel = cmds.ls(selection=True, transforms=True, long=True) or []
    if not sel:
        return (0, 0, 0)

    mirrored = flipped = skipped = 0
    with undo_chunk(f"Mirror Control {axis.upper()}"):
        for node in sel:
            counterpart = mirror_name(node.rpartition("|")[2])
            targets = []
            if counterpart:
                targets = [t for t in (cmds.ls(counterpart, long=True,
                                                type="transform") or [])
                           if t != node]
            if counterpart and len(targets) == 1:
                if _mirror_onto(node, targets[0], axis):
                    mirrored += 1
                else:
                    skipped += 1
            elif counterpart and len(targets) > 1:
                skipped += 1  # ambiguous — refuse to guess
            elif _flip_cvs_in_place(node, axis):
                flipped += 1
            else:
                skipped += 1
    log.debug("mirror: %d to opposite, %d flipped, %d skipped (axis=%s)",
              mirrored, flipped, skipped, axis)
    return (mirrored, flipped, skipped)


def set_selected_controls_color(rgb: tuple[float, float, float]) -> int:
    """Override the display colour of every selected control's curve shapes.

    Enables RGB colour override on each nurbsCurve shape of every selected
    transform and sets it to ``rgb`` (0-1 floats). Wrapped in one undo chunk,
    so the whole batch is a single Ctrl+Z. Returns the number of transforms
    recoloured (``0`` when nothing is selected).
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0
    with undo_chunk("Set Control Color"):
        for node in sel:
            shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                        fullPath=True) or []
            for sh in shapes:
                cmds.setAttr(f"{sh}.overrideEnabled", True)
                cmds.setAttr(f"{sh}.overrideRGBColors", True)
                cmds.setAttr(f"{sh}.overrideColorR", rgb[0])
                cmds.setAttr(f"{sh}.overrideColorG", rgb[1])
                cmds.setAttr(f"{sh}.overrideColorB", rgb[2])
    log.debug("set_selected_controls_color: %d control(s) -> %r", len(sel), rgb)
    return len(sel)


def reset_selected_controls_color() -> int:
    """Disable the colour override on every selected control's curve shapes.

    Restores each shape to its default (layer/draw-based) colour. Wrapped in
    one undo chunk. Returns the number of transforms reset (``0`` when nothing
    is selected).
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0
    with undo_chunk("Reset Control Color"):
        for node in sel:
            shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve",
                                        fullPath=True) or []
            for sh in shapes:
                cmds.setAttr(f"{sh}.overrideEnabled", False)
    log.debug("reset_selected_controls_color: %d control(s)", len(sel))
    return len(sel)


def drop_controls_at_origin(shapes: list[dict]) -> list[str]:
    """Create one control per shape dict, each centred at world origin.

    Used by the viewport drag-and-drop handler. For every shape:

    1. Build the control from the library dict.
    2. Normalise its scale to one unit.
    3. Offset its CVs so the geometry is centred at (0, 0, 0).
    4. Re-apply the library colour if one is stored.

    Wraps all creation in a single undo chunk and selects the created
    transforms at the end.

    Args:
        shapes: List of shape dicts (as returned by ``db.get_shape``).

    Returns:
        List of created Maya transform node names.
    """
    from app.core.shape_data import decode_color

    created: list[str] = []
    with undo_chunk("Drop Control"):
        for shape in shapes:
            node = Control.create_from_db(shape)
            ctrl = Control(name=node)
            ctrl.normalize_scale()

            bb = cmds.exactWorldBoundingBox(node)
            cx = (bb[0] + bb[3]) / 2.0
            cy = (bb[1] + bb[4]) / 2.0
            cz = (bb[2] + bb[5]) / 2.0
            for sh in (cmds.listRelatives(node, shapes=True) or []):
                cmds.move(
                    -cx, -cy, -cz, f"{sh}.cv[*]",
                    relative=True, worldSpace=True,
                )
            cmds.xform(node, centerPivots=True)

            color = decode_color(shape.get("color"))
            if color:
                ctrl.set_color(color)
            created.append(node)

    if created:
        cmds.select(created)
    return created
