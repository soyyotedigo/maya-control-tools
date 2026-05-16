"""Tests for ControlPresenter — exercise orchestration without a widget."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Inject the Maya mock before importing anything that references maya.cmds.
import app.compat
app.compat.ensure_maya_mock()

from app.presenters.control_presenter import ControlPresenter


class _FakeService:
    """Minimal stand-in for ShapeService — captures call args, no DB."""

    def __init__(self) -> None:
        self.imported_from: list[str] = []

    def import_database(self, src: str) -> None:
        self.imported_from.append(src)


# ---------------------------------------------------------------------------
# Selection sync re-entrance guard
# ---------------------------------------------------------------------------

class TestSelectionSync:
    def test_first_acquisition_returns_true(self):
        presenter = ControlPresenter(svc=_FakeService())
        with presenter.selection_sync() as acquired:
            assert acquired is True

    def test_nested_acquisition_returns_false(self):
        presenter = ControlPresenter(svc=_FakeService())
        with presenter.selection_sync() as outer:
            assert outer is True
            with presenter.selection_sync() as inner:
                assert inner is False

    def test_lock_released_after_with_block(self):
        presenter = ControlPresenter(svc=_FakeService())
        with presenter.selection_sync():
            pass
        # Should be acquirable again
        with presenter.selection_sync() as acquired:
            assert acquired is True

    def test_lock_released_on_exception(self):
        presenter = ControlPresenter(svc=_FakeService())
        with pytest.raises(RuntimeError):
            with presenter.selection_sync() as acquired:
                assert acquired is True
                raise RuntimeError("boom")
        # Despite the exception the guard must release.
        with presenter.selection_sync() as acquired:
            assert acquired is True


# ---------------------------------------------------------------------------
# Scale drag lifecycle — snapshot capture & incremental factor
# ---------------------------------------------------------------------------

class TestScaleDragLifecycle:
    def test_drag_start_captures_snapshots_and_opens_session(self):
        presenter = ControlPresenter(svc=_FakeService())
        ensure_mock = MagicMock()
        session_mock = MagicMock()
        with patch(
            "app.core.operations.ensure_snapshots_for_selection",
            ensure_mock,
        ), patch(
            "app.core.operations.ScaleDragSession.start",
            return_value=session_mock,
        ):
            presenter.scale_drag_start(slider_value=100)

        ensure_mock.assert_called_once_with(presenter._cv_snapshots)
        assert presenter._scale_drag_session is session_mock
        assert presenter._scale_drag_last == 100

    def test_drag_apply_uses_incremental_factor(self):
        presenter = ControlPresenter(svc=_FakeService())
        session_mock = MagicMock()
        presenter._scale_drag_session = session_mock
        presenter._scale_drag_last = 100

        presenter.scale_drag_apply(150)

        # 150 / 100 == 1.5
        session_mock.apply.assert_called_once_with(1.5)
        assert presenter._scale_drag_last == 150

    def test_drag_apply_skips_identity_and_zero(self):
        presenter = ControlPresenter(svc=_FakeService())
        session_mock = MagicMock()
        presenter._scale_drag_session = session_mock
        presenter._scale_drag_last = 100

        presenter.scale_drag_apply(100)  # identity
        presenter._scale_drag_last = 0
        presenter.scale_drag_apply(50)   # last <= 0 guard

        session_mock.apply.assert_not_called()

    def test_drag_apply_without_session_is_noop(self):
        presenter = ControlPresenter(svc=_FakeService())
        assert presenter._scale_drag_session is None
        # Must not raise.
        presenter.scale_drag_apply(150)

    def test_drag_end_closes_session_and_resets_state(self):
        presenter = ControlPresenter(svc=_FakeService())
        session_mock = MagicMock()
        presenter._scale_drag_session = session_mock
        presenter._scale_drag_last = 175

        presenter.scale_drag_end()

        session_mock.end.assert_called_once()
        assert presenter._scale_drag_session is None
        assert presenter._scale_drag_last == 100

    def test_drag_end_without_session_is_noop(self):
        presenter = ControlPresenter(svc=_FakeService())
        presenter.scale_drag_end()  # must not raise
        assert presenter._scale_drag_session is None


# ---------------------------------------------------------------------------
# scale_apply_manual / scale_reset
# ---------------------------------------------------------------------------

class TestManualScaleAndReset:
    def test_manual_apply_captures_snapshots_and_scales(self):
        presenter = ControlPresenter(svc=_FakeService())
        ensure_mock = MagicMock()
        scale_mock = MagicMock(return_value=3)
        with patch(
            "app.core.operations.ensure_snapshots_for_selection", ensure_mock,
        ), patch(
            "app.core.operations.scale_selected_cvs", scale_mock,
        ):
            count = presenter.scale_apply_manual(150)

        assert count == 3
        ensure_mock.assert_called_once_with(presenter._cv_snapshots)
        scale_mock.assert_called_once_with(1.5)

    def test_manual_apply_skips_non_positive_percent(self):
        presenter = ControlPresenter(svc=_FakeService())
        ensure_mock = MagicMock()
        scale_mock = MagicMock()
        with patch(
            "app.core.operations.ensure_snapshots_for_selection", ensure_mock,
        ), patch(
            "app.core.operations.scale_selected_cvs", scale_mock,
        ):
            count = presenter.scale_apply_manual(0)

        assert count == 0
        ensure_mock.assert_not_called()
        scale_mock.assert_not_called()

    def test_reset_delegates_to_reset_selected_cvs(self):
        presenter = ControlPresenter(svc=_FakeService())
        # Pre-seed snapshots so has_scale_snapshots reads true.
        presenter._cv_snapshots["arm_ctrl"] = {"shape1": [(0, 0, 0)]}
        reset_mock = MagicMock(return_value=1)
        with patch("app.core.operations.reset_selected_cvs", reset_mock):
            count = presenter.scale_reset()

        assert count == 1
        reset_mock.assert_called_once_with(presenter._cv_snapshots)
        assert presenter.has_scale_snapshots is True  # snapshots survive reset


# ---------------------------------------------------------------------------
# Library replacement broadcasts a signal so the view can re-render
# ---------------------------------------------------------------------------

class TestImportDatabaseSignal:
    def test_import_emits_library_replaced(self):
        svc = _FakeService()
        presenter = ControlPresenter(svc=svc)
        signal_seen: list[bool] = []
        presenter.library_replaced.connect(lambda: signal_seen.append(True))

        presenter.import_database("/tmp/x.db")

        assert svc.imported_from == ["/tmp/x.db"]
        assert signal_seen == [True]


# ---------------------------------------------------------------------------
# Replace / rotate / drop simply delegate (smoke tests)
# ---------------------------------------------------------------------------

class TestDelegation:
    def test_replace_returns_operation_count(self):
        presenter = ControlPresenter(svc=_FakeService())
        with patch(
            "app.core.operations.replace_controls_in_selection",
            return_value=2,
        ):
            assert presenter.replace_control_shape({"name": "x"}) == 2

    def test_replace_forwards_extract_to_mgear_flag(self):
        presenter = ControlPresenter(svc=_FakeService())
        replace_mock = MagicMock(return_value=1)
        with patch(
            "app.core.operations.replace_controls_in_selection", replace_mock
        ):
            presenter.replace_control_shape(
                {"name": "x"},
                replace_name=True,
                replace_color=False,
                extract_to_mgear=True,
            )

        replace_mock.assert_called_once_with(
            {"name": "x"},
            replace_name=True,
            replace_color=False,
            extract_to_mgear=True,
        )

    def test_rotate_returns_operation_count(self):
        presenter = ControlPresenter(svc=_FakeService())
        with patch(
            "app.core.operations.rotate_selected_cvs",
            return_value=1,
        ):
            assert presenter.rotate_cvs("x", 90) == 1

    def test_drop_skips_when_no_shapes(self):
        presenter = ControlPresenter(svc=_FakeService())
        drop_mock = MagicMock()
        with patch("app.core.operations.drop_controls_at_origin", drop_mock):
            result = presenter.create_controls_from_drop([])

        assert result == []
        drop_mock.assert_not_called()

    def test_drop_forwards_shapes(self):
        presenter = ControlPresenter(svc=_FakeService())
        drop_mock = MagicMock(return_value=["ctrl1", "ctrl2"])
        with patch("app.core.operations.drop_controls_at_origin", drop_mock):
            result = presenter.create_controls_from_drop([{"name": "a"}])

        assert result == ["ctrl1", "ctrl2"]
        drop_mock.assert_called_once()
