"""
ShapeService — decouples views from the database layer.

Views receive a ShapeService instance at construction and call methods
here instead of importing the database manager directly.
"""
from __future__ import annotations

import json

from app.database import manager as db


class ShapeService:
    """Thin wrapper around db.* calls for shape operations."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create tables and run schema migrations."""
        db.initialize()

    def seed_builtins(self) -> None:
        """Insert built-in shapes if not already present."""
        db.seed_builtins()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_shapes(self, search: str = "") -> list[dict]:
        """Return all shapes, optionally filtered by label substring."""
        shapes = db.get_all_shapes()
        if search:
            q = search.lower()
            shapes = [s for s in shapes if q in s["label"].lower()]
        return shapes

    def get_shape(self, name: str) -> dict | None:
        return db.get_shape(name)

    def get_shape_labels(self) -> dict:
        """Return an ordered {name: label} mapping of all shapes."""
        return db.get_shape_labels()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def save_shape(self, name: str, label: str, shapes_data: list[dict],
                   color=None) -> None:
        """Save a custom shape and optionally set its color."""
        db.save_custom_shape(name=name, label=label, shapes_data=shapes_data)
        if color is not None:
            db.update_shape_color(name, color)

    def update_color(self, name: str, rgb: tuple | None) -> None:
        """Save or clear the display color for a shape."""
        db.update_shape_color(name, rgb)

    def duplicate_shape(self, name: str) -> str | None:
        """Duplicate a shape and return the new name, or None on failure."""
        return db.duplicate_shape(name)

    def rename_shape(self, old: str, new_label: str) -> str:
        """Rename a shape's label and return the resulting new key."""
        return db.rename_shape(old, new_label)

    def delete_shape(self, name: str) -> None:
        db.delete_shape(name)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_shapes(self, path: str, names: list[str]) -> None:
        """Export named shapes to a JSON file."""
        shapes = [db.get_shape(n) for n in names]
        shapes = [s for s in shapes if s is not None]
        with open(path, "w") as f:
            json.dump(shapes, f, indent=2)

    def import_shapes(self, path: str) -> list[str]:
        """Import shapes from a JSON file; return list of imported names."""
        with open(path) as f:
            raw = json.load(f)
        imported: list[str] = []
        for s in raw:
            try:
                cv_raw = s.get("cv_data")
                cv = json.loads(cv_raw) if cv_raw else None
                if isinstance(cv, list):
                    shapes_data = [{
                        "cv_positions": cv,
                        "degree": s.get("degree", 1),
                        "knots": json.loads(s["knots"]) if s.get("knots") else None,
                    }]
                else:
                    shapes_data = [{"cv_positions": [], "degree": 1, "knots": None}]
                db.save_custom_shape(name=s["name"], label=s["label"],
                                     shapes_data=shapes_data)
                if s.get("color"):
                    db.update_shape_color(s["name"], json.loads(s["color"]))
                imported.append(s["name"])
            except Exception:
                pass
        return imported

    # ------------------------------------------------------------------
    # Whole-database file operations
    # ------------------------------------------------------------------

    def export_database(self, dest_path: str) -> None:
        """Copy the active SQLite database file to *dest_path*."""
        import shutil
        from app.paths import get_db_path
        shutil.copy2(get_db_path(), dest_path)

    def import_database(self, src_path: str) -> None:
        """Replace the active SQLite database with *src_path* and reinitialise.

        After the copy this runs ``initialize()`` so any pending schema
        migrations are applied on top of the imported file. Callers are
        expected to refresh their views after this call.
        """
        import shutil
        from app.paths import get_db_path
        shutil.copy2(src_path, get_db_path())
        self.initialize()
