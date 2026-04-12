"""
Control creation use-cases extracted from the main Qt view.

This module keeps Maya selection parsing and conversion logic out of UI
widgets so views can focus on dialogs and rendering updates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class ControlSelection:
    """Selection payload for creating a library control shape."""

    kind: str  # "curves", "edges", or "invalid"
    curve_transforms: list[str]
    edges: list[str]
    error: str | None = None


@dataclass(frozen=True)
class ControlCreationResult:
    """Result payload returned after converting selection to shapes_data."""

    ok: bool
    shapes_data: list[dict]
    created_control: str | None = None
    error: str | None = None


def normalize_shape_key(label: str) -> str:
    """Create a db-friendly key from a UI label."""
    return label.strip().lower().replace(" ", "_")


def unique_shape_identity(label: str, existing_names: set[str]) -> tuple[str, str]:
    """Return a unique (key, label) pair, adding numeric suffixes if needed."""
    clean_label = label.strip()
    key = normalize_shape_key(clean_label)
    if key not in existing_names:
        return key, clean_label

    counter = 1
    while f"{key}{counter}" in existing_names:
        counter += 1
    return f"{key}{counter}", f"{clean_label} {counter}"


def resolve_control_selection() -> ControlSelection:
    """Resolve current Maya selection into curves or edges for conversion."""
    maya_cmds = _get_cmds()
    curve_transforms = [
        t for t in (maya_cmds.ls(selection=True, transforms=True) or [])
        if maya_cmds.listRelatives(t, shapes=True, type="nurbsCurve")
    ]
    if curve_transforms:
        return ControlSelection(
            kind="curves",
            curve_transforms=curve_transforms,
            edges=[],
        )

    edges = _resolve_selection_to_edges()
    if edges:
        return ControlSelection(
            kind="edges",
            curve_transforms=[],
            edges=edges,
        )

    return ControlSelection(
        kind="invalid",
        curve_transforms=[],
        edges=[],
        error="Select a mesh object, edges, faces, or vertices first.",
    )


def create_shapes_from_selection(selection: ControlSelection) -> ControlCreationResult:
    """Convert a resolved selection into serializable shapes_data."""
    from app.core.operations import (
        create_control_from_curves,
        create_control_from_edges,
        undo_chunk,
    )

    if selection.kind == "curves":
        _, shapes_data = create_control_from_curves(selection.curve_transforms)
        if shapes_data:
            return ControlCreationResult(ok=True, shapes_data=shapes_data)
        return ControlCreationResult(ok=False, shapes_data=[], error="No curve data captured.")

    if selection.kind == "edges":
        maya_cmds = _get_cmds()
        with undo_chunk("Create Control"):
            try:
                ctrl, shapes_data = create_control_from_edges(selection.edges)
            except RuntimeError as exc:
                return ControlCreationResult(
                    ok=False,
                    shapes_data=[],
                    error=str(exc),
                )
            maya_cmds.select(ctrl.name)
            return ControlCreationResult(
                ok=True,
                shapes_data=shapes_data,
                created_control=ctrl.name,
            )

    return ControlCreationResult(
        ok=False,
        shapes_data=[],
        error=selection.error or "No valid selection.",
    )


def _resolve_selection_to_edges() -> list[str]:
    """Expand Maya component/object selection to a list of edge components."""
    maya_cmds = _get_cmds()
    edges: list[str] = maya_cmds.filterExpand(selectionMask=32, expand=True) or []

    if not edges:
        faces = maya_cmds.filterExpand(selectionMask=34, expand=True) or []
        if faces:
            converted = maya_cmds.polyListComponentConversion(
                faces,
                fromFace=True,
                toEdge=True,
            ) or []
            edges = maya_cmds.filterExpand(converted, selectionMask=32, expand=True) or []

    if not edges:
        verts = maya_cmds.filterExpand(selectionMask=31, expand=True) or []
        if verts:
            vert_indices = {int(v.split("[")[1].rstrip("]")) for v in verts}
            seen: set[str] = set()
            for v in verts:
                raw = maya_cmds.polyListComponentConversion(
                    v,
                    fromVertex=True,
                    toEdge=True,
                ) or []
                for edge in (maya_cmds.filterExpand(raw, selectionMask=32, expand=True) or []):
                    if edge in seen:
                        continue
                    seen.add(edge)
                    parts = maya_cmds.polyInfo(edge, edgeToVertex=True)[0].split()
                    if int(parts[2]) in vert_indices and int(parts[3]) in vert_indices:
                        edges.append(edge)

    if not edges:
        for t in (maya_cmds.ls(selection=True, transforms=True) or []):
            edges += maya_cmds.filterExpand(f"{t}.e[*]", selectionMask=32, expand=True) or []

    return edges


def _get_cmds() -> Any:
    """Return maya.cmds as Any to avoid strict type signature mismatches."""
    import maya.cmds as maya_cmds

    return cast(Any, maya_cmds)
