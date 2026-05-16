"""
ControlMe — Maya module installer (CLI).

Copies the repo into ``~/maya/<version>/modules/`` and writes a ``.mod``
file so Maya auto-adds the tool to ``sys.path`` and creates the shelf
button on every startup.

Usage:
    python install_module.py              # auto-detects newest Maya version
    python install_module.py --maya 2025

Safe to re-run — overwrites files in place.
"""
from __future__ import annotations

import argparse
import os
import sys

# Make ``module.installer`` importable when running this file directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from module.installer import (
    copy_package,
    find_maya_versions,
    modules_dir,
    read_app_version,
    write_mod_file,
)


def install(maya_version: str | None = None, src_dir: str | None = None) -> None:
    if src_dir is None:
        src_dir = _HERE

    if maya_version is None:
        versions = find_maya_versions()
        if not versions:
            sys.exit(
                "ERROR: No Maya version folders found under the Maya app dir.\n"
                "Pass --maya <version> explicitly, e.g.:\n"
                "  python install_module.py --maya 2025"
            )
        maya_version = versions[-1]
        print(f"Auto-detected Maya version: {maya_version}")

    modules = modules_dir(maya_version)
    install_dir = os.path.join(modules, "ControlMe")

    version = read_app_version(src_dir)
    print(f"Installing ControlMe v{version} → {install_dir}")
    copy_package(src_dir, install_dir)
    mod_path = write_mod_file(install_dir, modules, version)

    print(f"  .mod file : {mod_path}")
    print(f"  package   : {install_dir}")
    print()
    print("Done!  Restart Maya — the shelf button will appear automatically.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install ControlMe as a Maya module.")
    parser.add_argument(
        "--maya",
        metavar="VERSION",
        help="Maya version to install for (e.g. 2025). Auto-detected when omitted.",
    )
    args = parser.parse_args()
    install(args.maya)
