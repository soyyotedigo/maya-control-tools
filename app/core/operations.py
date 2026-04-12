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
from typing import Generator

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


def replace_control(node: str, shape: dict) -> None:
    """Swap the curve shape of a Maya control with a library shape.

    Preserves the existing object-space size, CV center offset, and
    guesses orientation from the flat axis of the old curve layout.

    Steps:

    1. Read old CVs in object space → extract size, center, flat axis.
    2. Build new shape from library (centred at origin, normalised to 1 unit).
    3. Rotate new shape so its flat axis matches the old one.
    4. Scale to match old object-space size.
    5. Swap shapes; offset CVs to restore old object-space center.
    6. Re-apply library color if stored.

    Args:
        node:  Existing Maya transform node name.
        shape: Shape dict from the database (as returned by ``db.get_shape``).
    """
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

    cmds.xform(node, centerPivots=True)

    # ── 6. Re-apply library color ─────────────────────────────────────────
    from app.core.shape_data import decode_color
    color = decode_color(shape.get("color"))
    if color:
        ctrl.set_color(color)

    log.debug("replace_control: replaced shape on %r", node)


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


# ---------------------------------------------------------------------------
# 6. Batch / selection-driven use cases
# ---------------------------------------------------------------------------

def replace_controls_in_selection(shape: dict) -> int:
    """Swap the curve shape of every selected Maya transform with *shape*.

    Wraps all swaps in a single undo chunk so the entire batch is
    reversible with one Ctrl+Z.

    Args:
        shape: Shape dict from the database (as returned by ``db.get_shape``).

    Returns:
        The number of transforms that were replaced (``0`` when nothing
        was selected — caller can show a warning).
    """
    sel = cmds.ls(selection=True, transforms=True) or []
    if not sel:
        return 0
    with undo_chunk("Replace Control"):
        for node in sel:
            replace_control(node, shape)
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
