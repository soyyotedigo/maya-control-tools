"""
ControlMe — drag-and-drop uninstaller for Maya.

Drag this file into Maya's viewport. Maya calls ``onMayaDroppedPythonFile``
which removes:

    * ~/Documents/maya/modules/ControlMe(.mod)              (global install)
    * ~/Documents/maya/<version>/modules/ControlMe(.mod)    (per-version installs)
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
    from module.installer import (
        find_maya_versions,
        global_modules_dir,
        modules_dir,
        remove_controlme_from,
    )

    # Every place an install could live: the global modules dir plus each
    # per-version one.
    targets = [global_modules_dir()]
    targets += [modules_dir(v) for v in find_maya_versions()]
    found = [m for m in targets
             if os.path.isdir(os.path.join(m, "ControlMe"))
             or os.path.isfile(os.path.join(m, "ControlMe.mod"))]

    if not found:
        cmds.confirmDialog(
            title="ControlMe Uninstaller",
            message=(
                "Nothing to uninstall — no ControlMe module found in the "
                "global or per-version modules folders.\n\n"
                "Shelf buttons and legacy userSetup.py entries will still be "
                "cleaned up."
            ),
            button=["OK"],
            defaultButton="OK",
        )

    locations = "\n".join("  • {}".format(m) for m in found) or "  • (none)"
    confirm = cmds.confirmDialog(
        title="Uninstall ControlMe?",
        message=(
            "This will remove the ControlMe module from:\n{}\n\n"
            "…plus any ControlMe shelf button and the legacy ControlMe line "
            "in userSetup.py (if present)."
        ).format(locations),
        button=["Uninstall", "Cancel"],
        defaultButton="Cancel",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if confirm != "Uninstall":
        print("ControlMe: uninstall cancelled.")
        return

    removed_locations = sum(1 for m in targets if remove_controlme_from(m))
    removed_buttons = _remove_shelf_buttons(cmds, mel)
    removed_usersetup = _clean_legacy_usersetup()

    cmds.confirmDialog(
        title="ControlMe Uninstalled",
        message=(
            "Removed:\n"
            "  • module folder + .mod file from {} location(s)\n"
            "  • {} shelf button(s)\n"
            "  • legacy userSetup.py line: {}\n\n"
            "Restart Maya so the .mod file fully unloads."
        ).format(removed_locations, removed_buttons,
                 "yes" if removed_usersetup else "n/a"),
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
