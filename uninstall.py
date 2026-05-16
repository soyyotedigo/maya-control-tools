"""
ControlMe — drag-and-drop uninstaller for Maya.

Drag this file into Maya's viewport. Maya calls ``onMayaDroppedPythonFile``
which removes:

    * ~/Documents/maya/<version>/modules/ControlMe/         (module folder)
    * ~/Documents/maya/<version>/modules/ControlMe.mod      (mod file)
    * any ControlMe shelf button on any shelf
    * the legacy ``# ControlMe`` line that older install.py versions wrote
      into ``~/Documents/maya/scripts/userSetup.py``
"""

import os
import sys


def onMayaDroppedPythonFile(obj):  # noqa: N802
    """Entry-point Maya calls when a .py file is dragged into the viewport."""
    _uninstall()


_MARKER = "ControlMe"


def _uninstall():
    try:
        import maya.cmds as cmds
        import maya.mel as mel
    except ImportError:
        print("=" * 60)
        print("  ControlMe — Uninstaller")
        print("  Must be run inside Maya. Drag uninstall.py into the viewport.")
        print("=" * 60)
        return

    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from module.installer import modules_dir, remove_module

    maya_version = cmds.about(version=True)
    modules = modules_dir(maya_version)
    install_dir = os.path.join(modules, "ControlMe")
    mod_file = os.path.join(modules, "ControlMe.mod")

    if not os.path.isdir(install_dir) and not os.path.isfile(mod_file):
        cmds.confirmDialog(
            title="ControlMe Uninstaller",
            message=(
                "Nothing to uninstall — no ControlMe module found at:\n{}\n\n"
                "Shelf buttons and legacy userSetup.py entries will still be "
                "cleaned up."
            ).format(install_dir),
            button=["OK"],
            defaultButton="OK",
        )

    confirm = cmds.confirmDialog(
        title="Uninstall ControlMe?",
        message=(
            "This will remove:\n"
            "  • {}\n"
            "  • {}\n"
            "  • any ControlMe shelf button\n"
            "  • the legacy ControlMe line in userSetup.py (if present)"
        ).format(install_dir, mod_file),
        button=["Uninstall", "Cancel"],
        defaultButton="Cancel",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if confirm != "Uninstall":
        print("ControlMe: uninstall cancelled.")
        return

    remove_module(install_dir, mod_file)
    removed_buttons = _remove_shelf_buttons(cmds, mel)
    removed_usersetup = _clean_legacy_usersetup()

    cmds.confirmDialog(
        title="ControlMe Uninstalled",
        message=(
            "Removed:\n"
            "  • module folder + .mod file\n"
            "  • {} shelf button(s)\n"
            "  • legacy userSetup.py line: {}\n\n"
            "Restart Maya so the .mod file fully unloads."
        ).format(removed_buttons, "yes" if removed_usersetup else "n/a"),
        button=["OK"],
        defaultButton="OK",
    )
    print("ControlMe: uninstall complete.")


def _remove_shelf_buttons(cmds, mel) -> int:
    """Delete every shelf button on every shelf whose annotation matches
    our marker. Returns the count removed."""
    try:
        top = mel.eval("$t=$gShelfTopLevel")
    except Exception:
        return 0
    if not top or not cmds.control(top, exists=True):
        return 0

    count = 0
    for tab in cmds.tabLayout(top, q=True, childArray=True) or []:
        for btn in cmds.shelfLayout(tab, q=True, childArray=True) or []:
            try:
                annotation = cmds.shelfButton(btn, q=True, annotation=True) or ""
            except Exception:
                continue
            if annotation == _MARKER:
                try:
                    cmds.deleteUI(btn)
                    count += 1
                except Exception:
                    pass
    return count


def _clean_legacy_usersetup() -> bool:
    """Remove the legacy ``# ControlMe`` line from the user's userSetup.py.

    Older versions of ``install.py`` appended a ``sys.path.insert`` line
    marked with ``# ControlMe``. The new installer uses a proper .mod
    file instead, so leftover entries should go. Returns True if a line
    was removed.
    """
    usersetup = os.path.join(
        os.path.expanduser("~"), "Documents", "maya", "scripts", "userSetup.py"
    )
    if not os.path.isfile(usersetup):
        return False
    try:
        with open(usersetup, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return False

    kept = [line for line in lines if "# {}".format(_MARKER) not in line]
    if len(kept) == len(lines):
        return False
    try:
        with open(usersetup, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    _uninstall()
