"""
ControlMe — drag-and-drop installer for Maya.

Drag this file into Maya's viewport. Maya calls ``onMayaDroppedPythonFile``
automatically, which installs ControlMe as a proper Maya module into the
version-independent modules folder, so it loads in every Maya version:

    ~/Documents/maya/modules/
        ControlMe.mod
        ControlMe/
            app/  config.toml  scripts/  icons/

Any older per-version install is removed first so Maya never loads two
copies. Re-running is safe — it overwrites in place. See
``install_module.py`` for the CLI equivalent.
"""

import os
import sys


def onMayaDroppedPythonFile(obj):  # noqa: N802
    """Entry-point Maya calls when a .py file is dragged into the viewport."""
    _install()


def _install():
    try:
        import maya.cmds as cmds
        import maya.mel as mel
    except ImportError:
        print("=" * 60)
        print("  ControlMe — Installer")
        print("  This installer must be run inside Maya.")
        print("  Drag install.py into the Maya viewport to install.")
        print("=" * 60)
        return

    src_dir = os.path.dirname(os.path.abspath(__file__))
    # Make the shared installer helpers importable when this file is
    # loaded via Maya's drag-and-drop.
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from module.installer import (
        copy_package,
        global_modules_dir,
        purge_per_version_installs,
        read_app_version,
        write_mod_file,
    )

    # Remove any older per-version installs so Maya doesn't load two copies.
    removed = purge_per_version_installs()

    modules = global_modules_dir()
    install_dir = os.path.join(modules, "ControlMe")
    version = read_app_version(src_dir)

    print("ControlMe: installing v{} → {}".format(version, install_dir))
    copy_package(src_dir, install_dir)
    mod_path = write_mod_file(install_dir, modules, version)

    # Put the install on sys.path for this Maya session so the shelf
    # button works immediately, without needing a restart.
    if install_dir not in sys.path:
        sys.path.insert(0, install_dir)

    _create_shelf_button(cmds, mel)

    migrated = (
        "\nRemoved {} older per-version install(s).".format(len(removed))
        if removed else ""
    )
    cmds.confirmDialog(
        title="ControlMe Installed",
        message=(
            "ControlMe v{} installed globally (loads in all Maya versions).\n\n"
            "Module : {}\n"
            ".mod   : {}\n{}\n"
            "A shelf button has been added to the active shelf.\n"
            "Restart Maya so the module loads on every startup."
        ).format(version, install_dir, mod_path, migrated),
        button=["OK"],
        defaultButton="OK",
    )
    print("ControlMe: installation complete.")


# Same launch command the module's userSetup.py uses — the .mod file
# puts the package on sys.path, so no install_dir argument is needed.
_LAUNCH_CMD = (
    "from app.views.main_view import show_as_workspace_control\n"
    "show_as_workspace_control()\n"
)
_MARKER = "ControlMe"


def _create_shelf_button(cmds, mel):
    """Add or refresh a ControlMe shelf button on the active shelf."""
    top = mel.eval("$t=$gShelfTopLevel")
    shelf = cmds.tabLayout(top, q=True, selectTab=True)

    # If a button with our marker already exists on this shelf, update it
    # in place rather than creating a duplicate.
    for btn in cmds.shelfLayout(shelf, q=True, childArray=True) or []:
        try:
            annotation = cmds.shelfButton(btn, q=True, annotation=True) or ""
        except Exception:
            continue
        if annotation == _MARKER:
            cmds.shelfButton(
                btn,
                e=True,
                label="ControlMe",
                image="controls_tool.png",
                annotation=_MARKER,
                sourceType="python",
                command=_LAUNCH_CMD,
            )
            return

    cmds.shelfButton(
        parent=shelf,
        label="ControlMe",
        image="controls_tool.png",
        annotation=_MARKER,
        sourceType="python",
        command=_LAUNCH_CMD,
    )


if __name__ == "__main__":
    _install()
