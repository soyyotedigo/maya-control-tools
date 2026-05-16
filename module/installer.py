"""
ControlMe — shared install / uninstall helpers.

Pure Python (no Maya imports) so the logic is unit-testable. Both the
CLI installer (``install_module.py``) and the drag-into-Maya installer
(``install.py``) call into this module; the drag-into-Maya uninstaller
(``uninstall.py``) reuses :func:`remove_module`.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from typing import List


# ---------------------------------------------------------------------------
# Maya user paths
# ---------------------------------------------------------------------------

def maya_app_dir() -> str:
    """Return the Maya user app directory for the current OS.

    Order of precedence:
      1. ``MAYA_APP_DIR`` environment variable.
      2. ``~/Documents/maya`` on Windows.
      3. ``~/maya`` on macOS and Linux.
    """
    override = os.environ.get("MAYA_APP_DIR")
    if override:
        return override
    if sys.platform == "win32":
        return os.path.join(os.path.expanduser("~"), "Documents", "maya")
    return os.path.join(os.path.expanduser("~"), "maya")


def modules_dir(maya_version: str) -> str:
    """Return the modules folder for a given Maya version."""
    return os.path.join(maya_app_dir(), maya_version, "modules")


def find_maya_versions() -> List[str]:
    """Return Maya versions found under the user app dir, sorted ascending."""
    root = maya_app_dir()
    if not os.path.isdir(root):
        return []
    versions = [
        name for name in os.listdir(root)
        if re.match(r"^\d{4}$", name) and os.path.isdir(os.path.join(root, name))
    ]
    return sorted(versions)


# ---------------------------------------------------------------------------
# Version + .mod file
# ---------------------------------------------------------------------------

def read_app_version(src_dir: str) -> str:
    """Read the app version from ``<src_dir>/config.toml``.

    Falls back to ``"0.0.0"`` when the file is missing or no TOML parser
    is available (Python <3.11 without ``tomli`` installed).
    """
    toml_path = os.path.join(src_dir, "config.toml")
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return "0.0.0"
    try:
        with open(toml_path, "rb") as fh:
            data = tomllib.load(fh)
        return str(data.get("app", {}).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def write_mod_file(install_dir: str, modules_dir_: str, version: str) -> str:
    """Write ``ControlMe.mod`` into ``modules_dir_`` from the template.

    Substitutes ``<INSTALL_DIR>`` with ``install_dir`` (forward slashes,
    Maya prefers them) and ``<VERSION>`` with ``version``. Returns the
    path of the written .mod file.
    """
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "ControlMe.mod"
    )
    with open(template_path, encoding="utf-8") as fh:
        content = fh.read()

    content = content.replace("<INSTALL_DIR>", install_dir.replace("\\", "/"))
    content = content.replace("<VERSION>", version)

    os.makedirs(modules_dir_, exist_ok=True)
    mod_path = os.path.join(modules_dir_, "ControlMe.mod")
    with open(mod_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return mod_path


# ---------------------------------------------------------------------------
# Package copy / remove
# ---------------------------------------------------------------------------

def copy_package(src_dir: str, install_dir: str) -> None:
    """Copy the runtime files from ``src_dir`` into ``install_dir``.

    Layout produced:
      <install_dir>/app/         (full app package)
      <install_dir>/scripts/     (module userSetup.py)
      <install_dir>/icons/       (controls_tool.png)
      <install_dir>/config.toml  (app config — was missing before)
    """
    # app/ package
    shutil.copytree(
        os.path.join(src_dir, "app"),
        os.path.join(install_dir, "app"),
        dirs_exist_ok=True,
    )
    # module userSetup.py → install_dir/scripts/
    shutil.copytree(
        os.path.join(src_dir, "module", "scripts"),
        os.path.join(install_dir, "scripts"),
        dirs_exist_ok=True,
    )
    # app config — read by app.config at import time
    toml_src = os.path.join(src_dir, "config.toml")
    if os.path.exists(toml_src):
        os.makedirs(install_dir, exist_ok=True)
        shutil.copy2(toml_src, os.path.join(install_dir, "config.toml"))
    # icon for the shelf button
    icon_src = os.path.join(src_dir, "app", "icons", "controls_tool.png")
    if os.path.exists(icon_src):
        icon_dst_dir = os.path.join(install_dir, "icons")
        os.makedirs(icon_dst_dir, exist_ok=True)
        shutil.copy2(icon_src, os.path.join(icon_dst_dir, "controls_tool.png"))


def remove_module(install_dir: str, mod_file: str) -> None:
    """Remove the installed module folder and its .mod file. Idempotent."""
    if os.path.isdir(install_dir):
        shutil.rmtree(install_dir, ignore_errors=True)
    if os.path.isfile(mod_file):
        try:
            os.remove(mod_file)
        except OSError:
            pass
