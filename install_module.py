"""
ControlMe — Maya module installer (CLI).

By default installs into the version-independent ``~/maya/modules/`` (or
``~/Documents/maya/modules/`` on Windows) and writes a ``.mod`` file, so
Maya auto-adds the tool to ``sys.path`` and creates the shelf button on
every startup — for all installed Maya versions at once.

Usage:
    python install_module.py              # global install (all Maya versions)
    python install_module.py --maya 2025  # per-version install instead

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
    global_modules_dir,
    modules_dir,
    purge_per_version_installs,
    read_app_version,
    write_mod_file,
)


def install(maya_version: str | None = None, src_dir: str | None = None) -> None:
    if src_dir is None:
        src_dir = _HERE

    if maya_version is None:
        # Global, version-independent install. Drop any older per-version
        # copies so Maya never loads two ControlMe modules.
        modules = global_modules_dir()
        removed = purge_per_version_installs()
        if removed:
            print(f"Removed {len(removed)} older per-version install(s).")
        print("Target: global modules dir (loads in all Maya versions)")
    else:
        modules = modules_dir(maya_version)
        print(f"Target: Maya {maya_version} (per-version install)")

    install_dir = os.path.join(modules, "ControlMe")

    version = read_app_version(src_dir)
    print(f"Installing ControlMe v{version} -> {install_dir}")
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
        help="Install for one Maya version (e.g. 2025) instead of the default "
             "global, all-versions install.",
    )
    args = parser.parse_args()
    install(args.maya)
