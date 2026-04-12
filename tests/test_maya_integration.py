"""Tests for app.views.maya_integration (outside Maya)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.compat import QtCore, QtWidgets
from app.views.images_view import _MIME_TYPE
from app.views.maya_integration import (
    ViewportDropFilter,
    install_viewport_drop,
    maya_main_window,
    show_as_workspace_control,
)


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mime_event(event_type, shape_key: str | None):
    """Build a mock QEvent whose mimeData carries an optional shape-key payload."""
    mime = MagicMock()
    mime.hasFormat.return_value = shape_key is not None
    if shape_key is not None:
        mime.data.return_value = shape_key.encode("utf-8")
    event = MagicMock()
    event.type.return_value = event_type
    event.mimeData.return_value = mime
    return event


# ---------------------------------------------------------------------------
# maya_main_window
# ---------------------------------------------------------------------------

def test_maya_main_window_returns_none_outside_maya():
    with patch("app.views.maya_integration.is_maya", return_value=False):
        assert maya_main_window() is None


# ---------------------------------------------------------------------------
# install_viewport_drop
# ---------------------------------------------------------------------------

def test_install_viewport_drop_returns_none_outside_maya(qapp):
    parent = QtWidgets.QWidget()
    with patch("app.views.maya_integration.is_maya", return_value=False):
        result = install_viewport_drop(parent, lambda key: None)
    parent.close()
    assert result is None


# ---------------------------------------------------------------------------
# ViewportDropFilter
# ---------------------------------------------------------------------------

class TestViewportDropFilter:
    @pytest.fixture
    def vp(self, qapp):
        w = QtWidgets.QWidget()
        yield w
        w.close()

    @pytest.fixture
    def drop_filter(self, vp):
        parent = QtWidgets.QWidget()
        flt = ViewportDropFilter([vp], parent=parent)
        yield flt
        parent.close()

    def test_drag_enter_accepts_correct_mime(self, drop_filter, vp):
        event = _make_mime_event(QtCore.QEvent.DragEnter, "circle")
        assert drop_filter.eventFilter(vp, event) is True
        event.acceptProposedAction.assert_called_once()

    def test_drag_enter_ignores_wrong_mime(self, drop_filter, vp):
        event = _make_mime_event(QtCore.QEvent.DragEnter, None)
        assert drop_filter.eventFilter(vp, event) is False

    def test_drag_move_accepts_correct_mime(self, drop_filter, vp):
        event = _make_mime_event(QtCore.QEvent.DragMove, "arrow")
        assert drop_filter.eventFilter(vp, event) is True
        event.acceptProposedAction.assert_called_once()

    def test_drop_emits_shape_dropped_signal(self, drop_filter, vp):
        received = []
        drop_filter.shape_dropped.connect(received.append)
        event = _make_mime_event(QtCore.QEvent.Drop, "cube")
        assert drop_filter.eventFilter(vp, event) is True
        assert received == ["cube"]

    def test_drop_ignores_wrong_mime(self, drop_filter, vp):
        received = []
        drop_filter.shape_dropped.connect(received.append)
        event = _make_mime_event(QtCore.QEvent.Drop, None)
        assert drop_filter.eventFilter(vp, event) is False
        assert received == []

    def test_unrelated_event_type_returns_false(self, drop_filter, vp):
        event = MagicMock()
        event.type.return_value = 99  # not DragEnter / DragMove / Drop
        assert drop_filter.eventFilter(vp, event) is False

    def test_viewport_has_accept_drops_set_on_init(self, qapp):
        vp = QtWidgets.QWidget()
        parent = QtWidgets.QWidget()
        ViewportDropFilter([vp], parent=parent)
        assert vp.acceptDrops() is True
        vp.close()
        parent.close()

    def test_multiple_viewports_all_have_accept_drops(self, qapp):
        vp1, vp2 = QtWidgets.QWidget(), QtWidgets.QWidget()
        parent = QtWidgets.QWidget()
        ViewportDropFilter([vp1, vp2], parent=parent)
        assert vp1.acceptDrops() is True
        assert vp2.acceptDrops() is True
        vp1.close()
        vp2.close()
        parent.close()


# ---------------------------------------------------------------------------
# show_as_workspace_control — outside Maya fallback path
# ---------------------------------------------------------------------------

def test_show_as_workspace_control_outside_maya_shows_window(qapp):
    """Outside Maya the function creates a plain ControlMe window and shows it."""
    with patch("app.views.maya_integration.is_maya", return_value=False):
        with patch("app.views.main_view.ControlMe") as MockControlMe:
            instance = MagicMock()
            MockControlMe.return_value = instance
            show_as_workspace_control()
    instance.show.assert_called_once()
