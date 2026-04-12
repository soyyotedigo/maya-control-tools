"""Helpers for encoding and decoding shape data stored in the database.

Removes repeated json.loads / json.dumps calls scattered across views
and operations code.
"""
from __future__ import annotations

import json


def decode_color(raw) -> tuple[float, float, float] | None:
    """Decode a DB color value to an (r, g, b) float tuple or None.

    Handles JSON strings, already-decoded lists/tuples, and None.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return tuple(raw)
    return tuple(json.loads(raw))


def encode_color(rgb: tuple) -> str:
    """Encode an (r, g, b) float tuple to a JSON string for DB storage."""
    return json.dumps(list(rgb))


def decode_cv_data(raw) -> list | dict | None:
    """Decode cv_data from a DB raw value to a Python object.

    Handles:
      - None            → None
      - list / dict     → returned as-is (already decoded)
      - JSON string     → parsed and returned
    """
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    return json.loads(raw)
