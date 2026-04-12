"""
ControlMe — Maya module installer.

Copies the repo into ~/maya/<version>/modules/ and writes a .mod file
so Maya auto-adds the tool to sys.path and creates the shelf button on
every startup — no drag-and-drop, no manual userSetup.py editing.

Usage:
    python install_module.py              # auto-detects Maya version
    python install_module.py --maya 2025

The installer is safe to re-run: it overwrites files in-place.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maya_app_dir() -> str:
    """Return the Maya user app directory for the current OS.

    Order of precedence:
      1. ``MAYA_APP_DIR`` environment variable (if set by the user).
      2. ``~/Documents/maya`` on Windows (Maya's default on Windows).
      3. ``~/maya`` on macOS and Linux.
    """
    override = os.environ.get("MAYA_APP_DIR")
    if override:
        return override
    if sys.platform == "win32":
        return os.path.join(os.path.expanduser("~"), "Documents", "maya")
    return os.path.join(os.path.expanduser("~"), "maya")


def _find_maya_versions() -> list[str]:
    """Return a sorted list of installed Maya versions found in the app dir."""
    maya_root = _maya_app_dir()
    if not os.path.isdir(maya_root):
        return []
    versions = []
    for name in os.listdir(maya_root):
        if re.match(r"^\d{4}$", name) and os.path.isdir(
            os.path.join(maya_root, name)
        ):
            versions.append(name)
    return sorted(versions)


def _modules_dir(maya_version: str) -> str:
    return os.path.join(_maya_app_dir(), maya_version, "modules")


def _read_version() -> str:
    """Read app version from config.toml; fall back to a safe default."""
    toml_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.toml"
    )
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


def _write_mod_file(install_dir: str, modules_dir: str) -> str:
    """Write ControlMe.mod with the correct absolute path. Returns mod path."""
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "module", "ControlMe.mod"
    )
    with open(template_path, encoding="utf-8") as fh:
        content = fh.read()

    content = content.replace("<INSTALL_DIR>", install_dir.replace("\\", "/"))
    os.makedirs(modules_dir, exist_ok=True)
    mod_path = os.path.join(modules_dir, "ControlMe.mod")
    with open(mod_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return mod_path


def _copy_package(src_dir: str, install_dir: str) -> None:
    """Copy app/, module/scripts/, and the icon into install_dir."""
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
    # icon
    icon_src = os.path.join(src_dir, "app", "icons", "controls_tool.png")
    if os.path.exists(icon_src):
        icon_dst_dir = os.path.join(install_dir, "icons")
        os.makedirs(icon_dst_dir, exist_ok=True)
        shutil.copy2(icon_src, os.path.join(icon_dst_dir, "controls_tool.png"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def install(maya_version: str | None = None) -> None:
    src_dir = os.path.dirname(os.path.abspath(__file__))

    if maya_version is None:
        versions = _find_maya_versions()
        if not versions:
            sys.exit(
                "ERROR: No Maya version folders found under ~/maya/.\n"
                "Pass --maya <version> explicitly, e.g.:\n"
                "  python install_module.py --maya 2025"
            )
        maya_version = versions[-1]  # use the newest
        print(f"Auto-detected Maya version: {maya_version}")

    modules_dir = _modules_dir(maya_version)
    install_dir = os.path.join(modules_dir, "ControlMe")

    version = _read_version()
    print(f"Installing ControlMe v{version} → {install_dir}")
    _copy_package(src_dir, install_dir)
    mod_path = _write_mod_file(install_dir, modules_dir)

    print(f"  .mod file : {mod_path}")
    print(f"  package   : {install_dir}")
    print()
    print("Done!  Restart Maya — the shelf button will appear automatically.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install ControlMe as a Maya module.")
    parser.add_argument(
        "--maya",
        metavar="VERSION",
        help="Maya version to install for (e.g. 2025).  Auto-detected when omitted.",
    )
    args = parser.parse_args()
    install(args.maya)
