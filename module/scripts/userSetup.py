"""
ControlMe — auto shelf setup via Maya module.

Maya executes all userSetup.py files found in module ``scripts/``
directories on startup.  This script adds a shelf button the first
time Maya loads the module and is a no-op on every subsequent launch.
"""
import maya.cmds as cmds
import maya.mel as mel


_MARKER = "ControlMe"
_MAX_ATTEMPTS = 25


def _launch_command():
    return (
        "from app.views.main_view import show_as_workspace_control\n"
        "show_as_workspace_control()\n"
    )


def _iter_shelf_buttons(top_level):
    tabs = cmds.tabLayout(top_level, q=True, childArray=True) or []
    for tab in tabs:
        buttons = cmds.shelfLayout(tab, q=True, childArray=True) or []
        for btn in buttons:
            yield tab, btn


def _create_or_update_button(target_shelf):
    launch_cmd = _launch_command()
    cmds.shelfButton(
        parent=target_shelf,
        label="ControlMe",
        image="controls_tool.png",
        annotation=_MARKER,
        sourceType="python",
        command=launch_cmd,
    )
    print("ControlMe: shelf button created.")


def _ensure_shelf_button(attempt=0):
    """Create or update ControlMe shelf button when Maya shelves are ready."""
    try:
        top = mel.eval("$t=$gShelfTopLevel")
    except Exception:
        top = ""

    if not top or not cmds.control(top, exists=True):
        if attempt < _MAX_ATTEMPTS:
            cmds.evalDeferred(lambda a=attempt + 1: _ensure_shelf_button(a))
        return

    tabs = cmds.tabLayout(top, q=True, childArray=True) or []
    if not tabs:
        if attempt < _MAX_ATTEMPTS:
            cmds.evalDeferred(lambda a=attempt + 1: _ensure_shelf_button(a))
        return

    launch_cmd = _launch_command()
    for _tab, btn in _iter_shelf_buttons(top):
        try:
            annotation = cmds.shelfButton(btn, q=True, annotation=True) or ""
            command = cmds.shelfButton(btn, q=True, command=True) or ""
        except Exception:
            continue

        if annotation == _MARKER or "show_as_workspace_control" in command:
            cmds.shelfButton(
                btn,
                e=True,
                label="ControlMe",
                image="controls_tool.png",
                annotation=_MARKER,
                sourceType="python",
                command=launch_cmd,
            )
            print("ControlMe: shelf button updated.")
            return

    target_shelf = "Custom"
    if not cmds.shelfLayout(target_shelf, exists=True):
        cmds.shelfLayout(target_shelf, parent=top)
    _create_or_update_button(target_shelf)


cmds.evalDeferred(_ensure_shelf_button)
