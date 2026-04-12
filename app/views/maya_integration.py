"""
Maya UI integration — keeps Maya/Qt plumbing out of ``ControlMe``.

Responsibilities:
  - Resolve the Maya main window as a ``QWidget`` parent.
  - Install a drop event filter on Maya viewports.
  - Create and restore the tool's ``workspaceControl`` (docking panel).

``ControlMe`` (``main_view.py``) imports only the small delegating
helpers from this module, so the widget itself never touches
``maya.OpenMayaUI`` or ``shiboken``.
"""
from __future__ import annotations

from typing import Callable

from app.compat import QtCore, QtWidgets, is_maya
from app.config import WINDOW_TITLE, WORKSPACE_CONTROL_NAME
from app.logger import log
from app.views.images_view import _MIME_TYPE

if is_maya():
    import maya.OpenMayaUI as omui

    try:
        from shiboken2 import wrapInstance  # Maya ≤ 2024 (PySide2)
    except ImportError:
        from shiboken6 import wrapInstance  # Maya 2025+ (PySide6)


# ---------------------------------------------------------------------------
# Main window resolution
# ---------------------------------------------------------------------------

def maya_main_window() -> QtWidgets.QWidget | None:
    """Return Maya's main window wrapped as a Qt widget, or ``None`` outside Maya."""
    if not is_maya():
        return None
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


# ---------------------------------------------------------------------------
# Viewport drag-and-drop
# ---------------------------------------------------------------------------

class ViewportDropFilter(QtCore.QObject):
    """Event filter installed on Maya viewport widgets.

    Accepts drops carrying a ``_MIME_TYPE`` payload and emits
    ``shape_dropped(key)`` so listeners can create a control.
    """

    shape_dropped = QtCore.Signal(str)

    def __init__(self, viewport_widgets, parent=None):
        super().__init__(parent)
        for vp in viewport_widgets:
            # Install on the panel widget and every child so the drop
            # lands regardless of which sub-widget the cursor is over.
            vp.setAcceptDrops(True)
            vp.installEventFilter(self)
            for child in vp.findChildren(QtWidgets.QWidget):
                child.setAcceptDrops(True)
                child.installEventFilter(self)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.DragEnter:
            if event.mimeData().hasFormat(_MIME_TYPE):
                event.acceptProposedAction()
                return True
        elif t == QtCore.QEvent.DragMove:
            if event.mimeData().hasFormat(_MIME_TYPE):
                event.acceptProposedAction()
                return True
        elif t == QtCore.QEvent.Drop:
            if event.mimeData().hasFormat(_MIME_TYPE):
                key = bytes(event.mimeData().data(_MIME_TYPE)).decode("utf-8")
                self.shape_dropped.emit(key)
                event.acceptProposedAction()
                return True
        return False


def install_viewport_drop(
    parent: QtWidgets.QWidget,
    on_drop: Callable[[str], None],
) -> ViewportDropFilter | None:
    """Install a drop filter on every Maya model panel viewport.

    Args:
        parent:  QObject that owns the filter (keeps it alive).
        on_drop: Callback invoked with the dragged shape key payload.

    Returns:
        The installed filter (store the reference to keep it alive) or
        ``None`` when running outside Maya or no model panels exist.
    """
    if not is_maya():
        return None
    try:
        import maya.cmds as cmds

        panels = cmds.getPanel(type="modelPanel") or []
        vp_widgets = []
        for panel in panels:
            ctrl = omui.MQtUtil.findControl(panel)
            if ctrl:
                vp_widgets.append(wrapInstance(int(ctrl), QtWidgets.QWidget))
        if not vp_widgets:
            log.warning("install_viewport_drop: no model panel widgets found")
            return None
        drop_filter = ViewportDropFilter(vp_widgets, parent=parent)
        drop_filter.shape_dropped.connect(on_drop)
        log.info(
            "install_viewport_drop: installed on %d viewport(s)", len(vp_widgets)
        )
        return drop_filter
    except Exception:
        log.exception("install_viewport_drop failed")
        return None


# ---------------------------------------------------------------------------
# workspaceControl docking
# ---------------------------------------------------------------------------

def show_as_workspace_control(
    install_dir: str | None = None, force_reload: bool = False
) -> None:
    """Open ControlMe as a fully dockable Maya workspaceControl.

    Behaves like native Maya panels (Outliner, Script Editor):
    - Can be docked, tabbed, or floated anywhere in the Maya UI.
    - Maya remembers its position across sessions (retain=True).

    Args:
        install_dir:  Path that contains the ``app/`` package.  Defaults
                      to the repo root inferred from this file's location.
        force_reload: When True the existing panel is destroyed and
                      recreated so hot-reloaded code takes effect.
                      Pass True from the Script Editor; leave False for
                      shelf-button / normal launches.

    Falls back to a plain floating window when called outside Maya.
    """
    import os

    if not is_maya():
        from app.views.main_view import ControlMe
        win = ControlMe()
        win.show()
        return

    import maya.cmds as cmds

    if install_dir is None:
        install_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    exists = cmds.workspaceControl(WORKSPACE_CONTROL_NAME, exists=True)

    if exists and not force_reload:
        # Panel already exists — just raise it and refresh the content.
        cmds.workspaceControl(WORKSPACE_CONTROL_NAME, edit=True, restore=True)
        _populate_workspace()
        return

    if exists:
        cmds.deleteUI(WORKSPACE_CONTROL_NAME)

    path_str = install_dir.replace("\\", "/")
    ui_script = (
        "import sys\n"
        "_p = r'{path}'\n"
        "if _p not in sys.path: sys.path.insert(0, _p)\n"
        "from app.views.maya_integration import _populate_workspace\n"
        "_populate_workspace()"
    ).format(path=path_str)

    cmds.workspaceControl(
        WORKSPACE_CONTROL_NAME,
        label=WINDOW_TITLE,
        dockToMainWindow=("right", 1),
        initialWidth=520,
        initialHeight=600,
        widthProperty="free",
        heightProperty="free",
        uiScript=ui_script,
        retain=True,  # saved in Maya's workspace layout → proper docking
    )
    _populate_workspace()


def _populate_workspace() -> None:
    """Fill the workspaceControl with a fresh ControlMe widget.

    Called by ``show_as_workspace_control`` on first creation and by
    Maya's ``uiScript`` whenever the panel is restored (e.g. after
    toggling visibility or reopening the workspace layout).
    """
    # Lazy import to avoid a circular dependency with main_view.
    from app.views.main_view import ControlMe

    ptr = omui.MQtUtil.findControl(WORKSPACE_CONTROL_NAME)
    if not ptr:
        return

    parent = wrapInstance(int(ptr), QtWidgets.QWidget)

    # Remove any previously embedded ControlMe widget.
    for child in parent.findChildren(ControlMe):
        child.setParent(None)
        child.deleteLater()

    if parent.layout() is None:
        layout = QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    widget = ControlMe(parent=parent, docked=True)
    widget.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding,
        QtWidgets.QSizePolicy.Expanding,
    )
    parent.layout().addWidget(widget)
    widget.show()
