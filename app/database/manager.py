"""
Database manager — SQLite persistence for the control shape library.

Stores built-in and custom user shapes. Custom shapes are saved from
the current Maya selection and can be browsed/applied like built-ins.
"""
import json
import os
import sqlite3

_CURRENT_VERSION = 5


def get_connection() -> sqlite3.Connection:
    from app.paths import get_db_path
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_db_if_needed() -> None:
    from app.paths import get_db_path
    db_path = get_db_path()
    if not os.path.exists(db_path):
        old = os.path.join(os.path.dirname(__file__), "controlme.db")
        if os.path.exists(old):
            import shutil
            shutil.copy2(old, db_path)


def initialize() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    _migrate_db_if_needed()
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS shapes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                label       TEXT    NOT NULL,
                cv_data     TEXT,
                cv_count    INTEGER NOT NULL DEFAULT 0,
                degree      INTEGER NOT NULL DEFAULT 1,
                knots       TEXT,
                position    TEXT,
                is_builtin  INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS groups (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT    NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS shape_groups (
                shape_id INTEGER REFERENCES shapes(id) ON DELETE CASCADE,
                group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
                PRIMARY KEY (shape_id, group_id)
            );

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deleted_builtins (
                name TEXT PRIMARY KEY
            );
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Run pending schema migrations."""
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row["version"] if row else 0

    if current < 2:
        # Add columns that may be missing from v1 schemas.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(shapes)").fetchall()}
        for col, definition in [
            ("cv_count",  "INTEGER NOT NULL DEFAULT 0"),
            ("degree",    "INTEGER NOT NULL DEFAULT 1"),
            ("knots",     "TEXT"),
            ("position",  "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE shapes ADD COLUMN {col} {definition}")

    if current < 3:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(shapes)").fetchall()}
        if "color" not in existing:
            conn.execute("ALTER TABLE shapes ADD COLUMN color TEXT")

    if current < 4:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(shapes)").fetchall()}
        if "sort_order" not in existing:
            conn.execute("ALTER TABLE shapes ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            # Initialize sort_order from current row order
            rows = conn.execute("SELECT id FROM shapes ORDER BY is_builtin DESC, label").fetchall()
            for i, row in enumerate(rows):
                conn.execute("UPDATE shapes SET sort_order = ? WHERE id = ?", (i, row["id"]))

    if current < 5:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deleted_builtins (
                name TEXT PRIMARY KEY
            )
        """)

    if current == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_CURRENT_VERSION,))
    elif current < _CURRENT_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (_CURRENT_VERSION,))


# ------------------------------------------------------------------
# Shapes
# ------------------------------------------------------------------

def get_all_shapes() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM shapes ORDER BY sort_order").fetchall()
    return [dict(r) for r in rows]


def get_shape_labels() -> dict:
    """Return an ordered {name: label} dict of all shapes from the DB."""
    return {s["name"]: s["label"] for s in get_all_shapes()}


def get_shape(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM shapes WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def save_custom_shape(
    name: str,
    label: str,
    shapes_data: list,
    position: tuple | None = None,
) -> int:
    """Save a user-defined shape captured from Maya.

    Args:
        name:        Unique key for the shape.
        label:       Human-readable display name.
        shapes_data: List of dicts with keys cv_positions, degree, knots.
                     Single-shape is stored as the old flat format for
                     backward compatibility; multi-shape uses the v2 format.
        position:    World-space position of the object (x, y, z).
    """
    first = shapes_data[0]
    degree = first.get("degree", 1)
    knots  = first.get("knots")

    if len(shapes_data) == 1:
        form = first.get("form", 0)
        cv_pts = [list(pt) for pt in first["cv_positions"]]
        cv_count = len(cv_pts)
        if form:
            # v1 wrapper preserves the closed/periodic flag.
            cv_json = json.dumps({"v": 1, "cv": cv_pts, "form": form})
        else:
            cv_json = json.dumps(cv_pts)
    else:
        payload = {
            "v": 2,
            "shapes": [
                {
                    "cv":     [list(pt) for pt in s["cv_positions"]],
                    "degree": s.get("degree", 1),
                    "knots":  s.get("knots"),
                    "form":   s.get("form", 0),
                }
                for s in shapes_data
            ],
        }
        cv_json  = json.dumps(payload)
        cv_count = sum(len(s["cv_positions"]) for s in shapes_data)

    knots_json = json.dumps(knots) if knots else None
    pos_json   = json.dumps(list(position)) if position else None

    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO shapes
               (name, label, cv_data, cv_count, degree, knots, position, is_builtin)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (name, label, cv_json, cv_count, degree, knots_json, pos_json),
        )
        return cur.lastrowid


def update_shape_color(name: str, rgb: tuple | None) -> None:
    """Save or clear the display color for a shape.

    Args:
        name: Shape key.
        rgb:  (r, g, b) floats in 0-1 range, or None to clear.
    """
    color_json = json.dumps(list(rgb)) if rgb else None
    with get_connection() as conn:
        conn.execute("UPDATE shapes SET color = ? WHERE name = ?", (color_json, name))


def duplicate_shape(name: str) -> str | None:
    """Duplicate a shape with an auto-incremented name (like Maya).

    The duplicate is inserted right after the source in sort order.
    Returns the new shape's name, or None if the source doesn't exist.
    """
    source = get_shape(name)
    if not source:
        return None

    # Find next available number suffix
    existing = {s["name"] for s in get_all_shapes()}
    base = name.rstrip("0123456789")
    counter = 1
    new_name = f"{base}{counter}"
    while new_name in existing:
        counter += 1
        new_name = f"{base}{counter}"

    new_label = source["label"].rstrip("0123456789").rstrip() + f" {counter}"
    src_order = source.get("sort_order", 0)

    with get_connection() as conn:
        # Push everything after the source down by 1
        conn.execute(
            "UPDATE shapes SET sort_order = sort_order + 1 WHERE sort_order > ?",
            (src_order,),
        )
        conn.execute(
            """INSERT INTO shapes
               (name, label, cv_data, cv_count, degree, knots, position, color,
                is_builtin, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (new_name, new_label, source["cv_data"], source["cv_count"],
             source["degree"], source["knots"], source["position"],
             source["color"], src_order + 1),
        )
    return new_name


def rename_shape(name: str, new_label: str) -> None:
    """Rename a shape's display label and key."""
    # Generate a key from the label
    new_name = new_label.lower().replace(" ", "_")
    existing = {s["name"] for s in get_all_shapes()}
    # Avoid collision (but allow keeping the same name)
    if new_name != name and new_name in existing:
        counter = 1
        while f"{new_name}{counter}" in existing:
            counter += 1
        new_name = f"{new_name}{counter}"

    with get_connection() as conn:
        conn.execute(
            "UPDATE shapes SET name = ?, label = ? WHERE name = ?",
            (new_name, new_label, name),
        )
    return new_name


def delete_shape(name: str) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_builtin FROM shapes WHERE name = ?", (name,)
        ).fetchone()
        if row and row["is_builtin"]:
            conn.execute(
                "INSERT OR IGNORE INTO deleted_builtins (name) VALUES (?)", (name,)
            )
        conn.execute("DELETE FROM shapes WHERE name = ?", (name,))


# ------------------------------------------------------------------
# Groups
# ------------------------------------------------------------------

def get_groups() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def create_group(name: str) -> int:
    with get_connection() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (name,))
        return cur.lastrowid


def assign_to_group(shape_name: str, group_name: str) -> None:
    shape = get_shape(shape_name)
    if not shape:
        return
    with get_connection() as conn:
        group = conn.execute("SELECT id FROM groups WHERE name = ?", (group_name,)).fetchone()
        if group:
            conn.execute(
                "INSERT OR IGNORE INTO shape_groups (shape_id, group_id) VALUES (?, ?)",
                (shape["id"], group["id"]),
            )


# ------------------------------------------------------------------
# Seed built-in shapes on first run
# ------------------------------------------------------------------

def seed_builtins() -> None:
    """Insert built-in shape data into DB if not already present."""
    from app.core.shapes import SHAPES, SHAPE_LABELS

    with get_connection() as conn:
        existing = {r["name"] for r in conn.execute("SELECT name FROM shapes").fetchall()}
        deleted  = {r["name"] for r in conn.execute("SELECT name FROM deleted_builtins").fetchall()}
        # Get next sort_order value
        row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS mx FROM shapes").fetchone()
        next_order = row["mx"] + 1
        for key, label in SHAPE_LABELS.items():
            shape = SHAPES.get(key, {})

            if shape.get("type") == "circle":
                cv_data = None
                cv_count = 8  # Maya circle default
                degree = 3
                knots_json = None
            else:
                points = shape.get("points", [])
                cv_data = json.dumps(points)
                cv_count = len(points)
                degree = shape.get("degree", 1)
                knots_json = json.dumps(shape["knots"]) if "knots" in shape else None

            if key not in existing and key not in deleted:
                conn.execute(
                    """INSERT INTO shapes
                       (name, label, cv_data, cv_count, degree, knots, position,
                        is_builtin, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                    (key, label, cv_data, cv_count, degree, knots_json, None, next_order),
                )
                next_order += 1
            elif key in existing:
                # Update existing built-ins with curve data if missing.
                conn.execute(
                    """UPDATE shapes
                       SET cv_data = COALESCE(cv_data, ?),
                           cv_count = CASE WHEN cv_count = 0 THEN ? ELSE cv_count END,
                           degree = CASE WHEN degree = 1 AND ? != 1 THEN ? ELSE degree END,
                           knots = COALESCE(knots, ?)
                       WHERE name = ? AND is_builtin = 1""",
                    (cv_data, cv_count, degree, degree, knots_json, key),
                )
