"""
Control — Maya rig control curve operations.

All public methods operate on Maya nodes via cmds.
This class is the bridge between the shape library and Maya.
"""
import maya.cmds as cmds
from app.core.shapes import SHAPES


class Control:
    """Represents a rig control curve in the Maya scene."""

    def __init__(self, name: str = "control"):
        self.name = name

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create(self, shape_type: str) -> str:
        """Create a new control curve from the shape library.

        Args:
            shape_type: Key from SHAPES dict (e.g. "circle", "arrow").

        Returns:
            The name of the created transform node.
        """
        if shape_type not in SHAPES:
            raise ValueError(f"Unknown shape type: '{shape_type}'. "
                             f"Available: {list(SHAPES.keys())}")

        data = SHAPES[shape_type]

        if data.get("type") == "circle":
            node = cmds.circle(
                name=f"{self.name}_CTRL",
                radius=data.get("radius", 1.0),
                normal=data.get("normal", (0, 1, 0)),
                constructionHistory=False,
            )[0]
        else:
            kwargs = {
                "name": f"{self.name}_CTRL",
                "degree": data.get("degree", 1),
                "point": data["points"],
            }
            if "knots" in data:
                kwargs["knot"] = data["knots"]
            node = cmds.curve(**kwargs)

            if "scale" in data:
                s = data["scale"]
                cmds.scale(s, s, s, node)
                cmds.makeIdentity(node, apply=True, t=1, r=1, s=1, n=0)

        cmds.xform(node, centerPivots=True)
        self.name = node
        return self.name

    # ------------------------------------------------------------------
    # Color
    # ------------------------------------------------------------------

    def set_color(self, rgb: tuple) -> None:
        """Override the display color of the control's shapes.

        Args:
            rgb: Tuple of (r, g, b) floats in 0-1 range.
        """
        shapes = cmds.listRelatives(self.name, shapes=True) or []
        for shape in shapes:
            cmds.setAttr(f"{shape}.overrideEnabled", True)
            cmds.setAttr(f"{shape}.overrideRGBColors", True)
            cmds.setAttr(f"{shape}.overrideColorR", rgb[0])
            cmds.setAttr(f"{shape}.overrideColorG", rgb[1])
            cmds.setAttr(f"{shape}.overrideColorB", rgb[2])

    # ------------------------------------------------------------------
    # Geometry queries
    # ------------------------------------------------------------------

    def get_shapes(self) -> list:
        return cmds.listRelatives(self.name, shapes=True) or []

    def get_bounding_box(self) -> tuple:
        return cmds.exactWorldBoundingBox(self.name)

    def get_dimensions(self) -> tuple:
        bb = self.get_bounding_box()
        return bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]

    def get_max_dimension(self) -> float:
        return max(self.get_dimensions())

    def get_scale_factor(self) -> float:
        max_dim = self.get_max_dimension()
        return 0.0 if max_dim == 0 else 1.0 / max_dim

    def normalize_scale(self) -> None:
        """Scale the control so its largest dimension is 1 unit."""
        factor = self.get_scale_factor()
        if factor:
            cmds.scale(factor, factor, factor, self.name)
            cmds.makeIdentity(self.name, apply=True, t=1, r=1, s=1, n=0)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def get_cv_positions(self) -> list:
        """Return CV world positions as a list of (x, y, z) tuples.

        Uses openMaya API 2.0 (MFnNurbsCurve) for a single bulk read instead of
        one cmds.xform call per CV.  Falls back to cmds in standalone/mock mode.
        """
        shapes = self.get_shapes()
        if not shapes:
            return []
        try:
            from maya.api import OpenMaya as om
            sel = om.MSelectionList()
            sel.add(shapes[0])
            fn = om.MFnNurbsCurve(sel.getDagPath(0))
            if not isinstance(fn.degree, int):
                raise TypeError("OM2 not available in this context")
            return [(p.x, p.y, p.z) for p in fn.cvPositions(om.MSpace.kWorld)]
        except Exception:
            cvs = cmds.ls(f"{shapes[0]}.cv[*]", flatten=True)
            return [tuple(cmds.xform(cv, query=True, worldSpace=True, translation=True))
                    for cv in cvs]

    def get_all_shapes_data(self) -> list:
        """Return a list of dicts, one per NurbsCurve shape under this transform.

        Each dict has: cv_positions (list of (x,y,z)), degree (int), knots (list).

        Uses openMaya API 2.0 (MFnNurbsCurve) for bulk CV + knot reads.
        Falls back to cmds in standalone/mock mode.
        """
        result = []
        for shape in self.get_shapes():
            try:
                from maya.api import OpenMaya as om
                sel = om.MSelectionList()
                sel.add(shape)
                fn = om.MFnNurbsCurve(sel.getDagPath(0))
                cv_pos = [(p.x, p.y, p.z) for p in fn.cvPositions(om.MSpace.kWorld)]
                degree = fn.degree
                knots  = list(fn.knots())           # actual stored knot vector
                form   = cmds.getAttr(f"{shape}.form")
            except Exception:
                cvs = cmds.ls(f"{shape}.cv[*]", flatten=True)
                cv_pos = [
                    tuple(cmds.xform(cv, query=True, worldSpace=True, translation=True))
                    for cv in cvs
                ]
                degree = cmds.getAttr(f"{shape}.degree")
                form   = cmds.getAttr(f"{shape}.form")
                knots  = list(range(len(cv_pos) + degree - 1))
            result.append({
                "cv_positions": cv_pos,
                "degree": degree,
                "knots": knots,
                "form": form,
            })
        return result

    def get_position(self) -> tuple:
        """Return the world-space position of the transform node."""
        pos = cmds.xform(self.name, query=True, worldSpace=True, translation=True)
        return tuple(pos)

    def get_degree(self) -> int:
        """Return the degree of the first curve shape."""
        shapes = self.get_shapes()
        if not shapes:
            return 1
        return cmds.getAttr(f"{shapes[0]}.degree")

    def get_knots(self) -> list:
        """Return the knot vector of the first curve shape."""
        shapes = self.get_shapes()
        if not shapes:
            return []
        cvs = cmds.ls(f"{shapes[0]}.cv[*]", flatten=True)
        degree = cmds.getAttr(f"{shapes[0]}.degree")
        # Maya requires: len(knots) == len(CVs) + degree - 1
        return list(range(len(cvs) + degree - 1))

    def to_dict(self) -> dict:
        """Serialize control data for saving to the library."""
        cv_positions = self.get_cv_positions()
        return {
            "name": self.name,
            "cv_positions": cv_positions,
            "cv_count": len(cv_positions),
            "degree": self.get_degree(),
            "knots": self.get_knots(),
            "position": self.get_position(),
            "bounding_box": self.get_bounding_box(),
        }

    # ------------------------------------------------------------------
    # Class helpers
    # ------------------------------------------------------------------

    @classmethod
    def create_from_db(cls, shape_dict: dict) -> str:
        """Create a Maya curve from a database shape dict.

        Uses the stored CV positions and degree rather than the static
        SHAPES dict, so custom user shapes are supported too.

        Returns:
            The name of the created transform node.
        """
        import json

        label = shape_dict.get("label", "control")
        node_name = label.replace(" ", "_") + "_CTRL"

        # ``shapes`` key: list of dicts from get_all_shapes_data() — used when
        # replace_control is called with a live-captured shape rather than a DB row.
        shapes_list = shape_dict.get("shapes")
        if shapes_list:
            node = cmds.createNode("transform", name=node_name)
            for s_data in shapes_list:
                pts = [list(p) for p in s_data["cv_positions"]]
                d = s_data.get("degree", 1)
                form = s_data.get("form", 0)
                k = s_data.get("knots")
                kwargs = {"degree": d, "point": pts}
                if k and len(k) == len(pts) + d - 1:
                    kwargs["knot"] = k
                if form == 2:
                    kwargs["periodic"] = True
                curve = cmds.curve(**kwargs)
                if form == 1:
                    cmds.closeCurve(curve, ch=False, preserveShape=1,
                                    replaceOriginal=True)
                for sh in (cmds.listRelatives(curve, shapes=True) or []):
                    cmds.parent(sh, node, relative=True, shape=True)
                cmds.delete(curve)
            cmds.xform(node, centerPivots=True)
            return node

        cv_raw = json.loads(shape_dict["cv_data"]) if shape_dict.get("cv_data") else None
        degree = shape_dict.get("degree", 1)
        knots_raw = shape_dict.get("knots")
        knots = json.loads(knots_raw) if knots_raw else None

        # Unwrap v1 single-shape format (carries a form flag).
        single_form = 0
        if isinstance(cv_raw, dict) and cv_raw.get("v") == 1:
            single_form = cv_raw.get("form", 0)
            cv_raw = cv_raw["cv"]

        if cv_raw is None:
            # Circle — no CV data stored, use cmds.circle
            node = cmds.circle(
                name=node_name,
                radius=1.0,
                normal=(0, 1, 0),
                constructionHistory=False,
            )[0]
        elif isinstance(cv_raw, dict) and cv_raw.get("v") == 2:
            # Multi-shape: create a transform and parent each curve as a shape.
            node = cmds.createNode("transform", name=node_name)
            for s_data in cv_raw["shapes"]:
                d    = s_data.get("degree", 1)
                pts  = s_data["cv"]
                form = s_data.get("form", 0)
                kwargs = {"degree": d, "point": pts}
                k = s_data.get("knots")
                # Guard: only pass knots when the stored length is correct.
                if k and len(k) == len(pts) + d - 1:
                    kwargs["knot"] = k
                # form=2 (periodic) → use cmds.curve(periodic=True) directly.
                # This avoids creating an open curve then calling closeCurve,
                # which would distort the shape (preserveShape=0 is lossy).
                if form == 2:
                    kwargs["periodic"] = True
                curve = cmds.curve(**kwargs)
                if form == 1:
                    # form=1 (closed, non-periodic): connect endpoints only.
                    cmds.closeCurve(curve, ch=False, preserveShape=1,
                                    replaceOriginal=True)
                for sh in (cmds.listRelatives(curve, shapes=True) or []):
                    cmds.parent(sh, node, relative=True, shape=True)
                cmds.delete(curve)
        else:
            kwargs = {"name": node_name, "degree": degree, "point": cv_raw}
            # Guard: only pass knots when the stored length is correct.
            if knots and len(knots) == len(cv_raw) + degree - 1:
                kwargs["knot"] = knots
            if single_form == 2:
                # Periodic: pass periodic=True so the curve is created
                # correctly in one step, avoiding the open→closeCurve path
                # that distorts the shape.
                kwargs["periodic"] = True
            node = cmds.curve(**kwargs)
            if single_form == 1:
                # Closed (non-periodic): connect endpoints, preserve shape.
                cmds.closeCurve(node, ch=False, preserveShape=1,
                                replaceOriginal=True)

        cmds.xform(node, centerPivots=True)
        return node
