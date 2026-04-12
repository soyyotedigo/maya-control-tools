"""
OpenMaya API 2.0 utilities — fast path for geometry operations.

All functions here use maya.api.OpenMaya (OM2) instead of maya.cmds for
performance-critical operations.  OM2 avoids the MEL interpreter overhead,
works directly with C++ objects, and is the industry-standard approach for
production-quality Maya tools.

Import guard: this module is always imported inside Maya, never in standalone.
"""
from __future__ import annotations

import maya.api.OpenMaya as om


# ---------------------------------------------------------------------------
# DAG helpers
# ---------------------------------------------------------------------------

def dag_path_from_name(name: str) -> om.MDagPath:
    """Return an MDagPath for *name* (transform or shape node)."""
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDagPath(0)


# ---------------------------------------------------------------------------
# Mesh queries
# ---------------------------------------------------------------------------

def get_mesh_edge_vertices(mesh: str, edge_id: int) -> tuple[int, int]:
    """Return ``(v0, v1)`` vertex indices for a mesh edge.

    Replaces::
        cmds.polyInfo(edge, edgeToVertex=True)

    Args:
        mesh:     Transform or shape node name of the polygon mesh.
        edge_id:  Zero-based edge index.

    Returns:
        Tuple of two vertex indices.
    """
    fn = om.MFnMesh(dag_path_from_name(mesh))
    v0, v1 = fn.getEdgeVertices(edge_id)
    return int(v0), int(v1)


def get_vertex_world_position(mesh: str, vertex_id: int) -> tuple[float, float, float]:
    """Return world-space ``(x, y, z)`` for a mesh vertex.

    Replaces::
        cmds.pointPosition(f"{mesh}.vtx[{v}", world=True)

    Args:
        mesh:       Transform or shape node name of the polygon mesh.
        vertex_id:  Zero-based vertex index.

    Returns:
        Tuple ``(x, y, z)`` in world space.
    """
    fn = om.MFnMesh(dag_path_from_name(mesh))
    pt = fn.getPoint(vertex_id, om.MSpace.kWorld)
    return (pt.x, pt.y, pt.z)


# ---------------------------------------------------------------------------
# NURBS curve operations
# ---------------------------------------------------------------------------

def create_nurbs_curve(
    points: list[tuple[float, float, float]],
    knots: list[float],
    degree: int,
    periodic: bool = False,
) -> str:
    """Create a NURBS curve via MFnNurbsCurve. Returns transform node name.

    Replaces::
        cmds.curve(p=pts, k=knots, d=deg)

    Args:
        points:   CV positions as (x, y, z) tuples.
        knots:    Knot vector.
        degree:   Curve degree (1 = linear, 3 = cubic).
        periodic: True for a closed/periodic curve.

    Returns:
        Short name of the created transform node.
    """
    m_points = om.MPointArray([om.MPoint(*p) for p in points])
    m_knots = om.MDoubleArray(knots)
    form = om.MFnNurbsCurve.kPeriodic if periodic else om.MFnNurbsCurve.kOpen
    fn = om.MFnNurbsCurve()
    fn.create(m_points, m_knots, degree, form, False, True, om.MObject.kNullObj)
    dag = om.MDagPath.getAPathTo(fn.parent(0))
    return dag.partialPathName()


def get_nurbs_cv_positions(
    curve: str,
    space: int | None = None,
) -> list[tuple[float, float, float]]:
    """Extract CV positions from a NURBS curve transform or shape node.

    Replaces::
        cmds.xform(f"{sh}.cv[*]", q=True, t=True, os=True)

    Args:
        curve: Transform or shape node name.
        space: ``om.MSpace`` constant (defaults to ``kObject``).

    Returns:
        List of ``(x, y, z)`` tuples, one per CV.
    """
    if space is None:
        space = om.MSpace.kObject
    fn = om.MFnNurbsCurve(dag_path_from_name(curve))
    return [(p.x, p.y, p.z) for p in fn.cvPositions(space)]


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------

def get_bounding_box(dag_node: str) -> om.MBoundingBox:
    """Return the local-space MBoundingBox for a DAG node.

    Replaces::
        cmds.exactWorldBoundingBox(node)   # (world-space variant)

    Note: MBoundingBox.min/max are in the node's local space.  For world
    space, iterate over shapes and use MFnNurbsCurve.boundingBox() after
    applying the world matrix, or continue to use cmds.exactWorldBoundingBox
    for the world-space path.

    Args:
        dag_node: Transform or shape node name.

    Returns:
        ``om.MBoundingBox`` with ``min`` and ``max`` MPoint attributes.
    """
    dag = dag_path_from_name(dag_node)
    fn = om.MFnDagNode(dag)
    return fn.boundingBox
