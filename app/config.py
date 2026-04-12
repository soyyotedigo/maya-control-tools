"""
Central configuration loader for ControlMe.

Reads config.toml from the repo root. Falls back to built-in defaults
silently if the file is missing or tomllib/tomli is not available.

Maya 2024 (Python 3.10): requires `mayapy -m pip install tomli` for TOML support.
Maya 2025+ (Python 3.11): tomllib is in the standard library.
"""

from pathlib import Path

_TOML_PATH = Path(__file__).parent.parent / "config.toml"

_cfg: dict = {}

try:
    import tomllib  # Python 3.11+

    with open(_TOML_PATH, "rb") as _f:
        _cfg = tomllib.load(_f)
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli (Python 3.10)

        with open(_TOML_PATH, "rb") as _f:
            _cfg = tomllib.load(_f)
    except ImportError:
        pass  # No TOML parser available — use defaults below
except Exception:
    pass  # File missing or malformed — use defaults silently


def _get(section: str, key: str, default):
    return _cfg.get(section, {}).get(key, default)


# ── App ───────────────────────────────────────────────────────────────────────
VERSION = _get("app", "version", "1.5.6")
WINDOW_TITLE = _get("app", "window_title", "ControlMe")
AUTHOR = _get("app", "author", "Cesar Daniel Franco")
MIN_WIDTH = _get("app", "min_width", 500)
MIN_HEIGHT = _get("app", "min_height", 400)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_MAX_BYTES = _get("logging", "max_bytes", 5242880)
LOG_BACKUP_COUNT = _get("logging", "backup_count", 5)
LOG_FILE_LEVEL = _get("logging", "file_level", "DEBUG")
LOG_CONSOLE_LEVEL = _get("logging", "console_level", "INFO")

# ── Thumbnails ────────────────────────────────────────────────────────────────
THUMBNAIL_CACHE_SIZE = _get("thumbnails", "lru_cache_size", 256)

# ── Maya internal identifiers (not user-editable — must not change) ───────────
SETTINGS_KEY = "ControlMe"
WORKSPACE_CONTROL_NAME = "ControlMeWorkspaceControl"
