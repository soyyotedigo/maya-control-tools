"""
ControlMe — drag-and-drop installer for Maya.

.. deprecated:: 1.4.0
    This installer is superseded by ``install_module.py``, which installs
    ControlMe as a proper Maya module (.mod) and auto-creates the shelf
    button on every Maya startup without any userSetup.py editing::

        python install_module.py              # auto-detects Maya version
        python install_module.py --maya 2025

    This file is kept for backwards compatibility and will be removed in a
    future release.

Drag this file into Maya's viewport to install the ControlMe.
Maya will call ``onMayaDroppedPythonFile`` automatically.

Running this script outside Maya prints a friendly error and exits.
"""

import os
import sys
import shutil


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
        print("=" * 60)
        print("  This installer must be run inside Maya.")
        print("  Drag install.py into the Maya viewport to install.")
        print("=" * 60)
        return

    src_dir = os.path.dirname(os.path.abspath(__file__))
    install_dir = cmds.internalVar(userScriptDir=True) + "maya-control-tools/"

    print("ControlMe: installing to {} ...".format(install_dir))

    _copy_files(src_dir, install_dir)
    _copy_icon(src_dir, cmds)
    _setup_usersetup(install_dir)

    if install_dir not in sys.path:
        sys.path.insert(0, install_dir)

    _create_shelf_button(install_dir, cmds, mel)

    cmds.confirmDialog(
        title="ControlMe Installed",
        message=(
            "ControlMe installed successfully!\n\n"
            "Location:\n{}\n\n"
            "A shelf button has been added to the active shelf.\n"
            "Restart Maya so the path is registered on startup."
        ).format(install_dir),
        button=["OK"],
        defaultButton="OK",
    )
    print("ControlMe: installation complete.")


def _copy_files(src_dir, install_dir):
    """Copy app/ into install_dir, updating any existing files cleanly."""
    src_app = os.path.join(src_dir, "app")
    dst_app = os.path.join(install_dir, "app")
    shutil.copytree(src_app, dst_app, dirs_exist_ok=True)


def _copy_icon(src_dir, cmds):
    """Copy controls_tool.png to Maya's userBitmapsDir."""
    src_icon = os.path.join(src_dir, "app", "icons", "controls_tool.png")
    if not os.path.exists(src_icon):
        print("ControlMe: icon not found at {}, skipping.".format(src_icon))
        return
    bitmaps_dir = cmds.internalVar(userBitmapsDir=True)
    os.makedirs(bitmaps_dir, exist_ok=True)
    shutil.copy2(src_icon, os.path.join(bitmaps_dir, "controls_tool.png"))


def _setup_usersetup(install_dir):
    """Append a sys.path entry to userSetup.py (idempotent — never duplicates)."""
    marker = "# ControlMe"
    path_str = install_dir.replace("\\", "/").rstrip("/")
    line = 'import sys; sys.path.insert(0, r"{}")  {}'.format(path_str, marker)

    usersetup = os.path.join(
        os.path.expanduser("~"), "Documents", "maya", "scripts", "userSetup.py"
    )
    os.makedirs(os.path.dirname(usersetup), exist_ok=True)

    if os.path.exists(usersetup):
        with open(usersetup, "r", encoding="utf-8") as fh:
            if marker in fh.read():
                return  # already registered

    with open(usersetup, "a", encoding="utf-8") as fh:
        fh.write("\n{}\n".format(line))


# Command string embedded in the shelf button — runs when the user clicks it.
# Uses show_as_workspace_control so the panel is properly dockable in Maya.
_LAUNCH_TEMPLATE = (
    "import sys\n"
    '_p = r"{path}"\n'
    "if _p not in sys.path: sys.path.insert(0, _p)\n"
    "from app.views.main_view import show_as_workspace_control\n"
    "show_as_workspace_control(install_dir=_p)\n"
)


def _create_shelf_button(install_dir, cmds, mel):
    """Add a shelf button on the currently active Maya shelf tab."""
    path_str = install_dir.replace("\\", "/").rstrip("/")
    launch_cmd = _LAUNCH_TEMPLATE.format(path=path_str)

    top = mel.eval("$t=$gShelfTopLevel")
    shelf = cmds.tabLayout(top, q=True, selectTab=True)
    cmds.shelfButton(
        parent=shelf,
        label="Controls",
        image="controls_tool.png",
        annotation="ControlMe \u2014 open control shape manager",
        sourceType="python",
        command=launch_cmd,
    )


if __name__ == "__main__":
    _install()
