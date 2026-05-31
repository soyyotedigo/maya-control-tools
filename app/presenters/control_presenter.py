"""
ControlPresenter — orchestration layer between ControlMe (view) and the
core operations / ShapeService.

Why a presenter
---------------
The view (``app.views.main_view.ControlMe``) used to import seven distinct
helpers from ``app.core.operations`` lazily inside its method bodies, hold
operation-critical state (CV snapshots, drag sessions, selection-sync
guards) as widget attributes, and orchestrate undo chunks. Moving all of
that here gives us:

- a single seam to mock when testing Maya orchestration (no QWidget needed)
- one place where transient state lives, so the Reset button does not
  depend on widget lifetime
- a view that is short enough to read top-to-bottom and only does UI

The presenter is a ``QtCore.QObject`` so it can be parented to the view
and emit Qt signals; it never imports widgets, dialogs, or pixmaps.
"""
from __future__ import annotations

from typing import Callable

from app.compat import QtCore
from app.core.shape_service import ShapeService


class _SelectionSyncCtx:
    """Context manager that re-enters only once.

    Used to guard the outliner↔image-grid mirror handlers from each other:
    the first ``with`` acquires the lock and yields True; any nested call
    yields False so the inner handler exits early.
    """

    def __init__(self, presenter: "ControlPresenter") -> None:
        self._presenter = presenter
        self._acquired = False

    def __enter__(self) -> bool:
        if self._presenter._syncing:
            return False
        self._presenter._syncing = True
        self._acquired = True
        return True

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._acquired:
            self._presenter._syncing = False


class ControlPresenter(QtCore.QObject):
    """Orchestrates Maya operations for the ControlMe window."""

    # Emitted whenever the shape library is mutated wholesale (DB import).
    # Granular mutations (save/duplicate/rename/delete) update the view via
    # explicit calls — they don't need this broadcast.
    library_replaced = QtCore.Signal()

    def __init__(self, svc: ShapeService, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._svc = svc
        # CV snapshots keyed by node name. Populated lazily before any scale
        # so ``scale_reset`` can restore original positions even after many
        # scale gestures. Survives across method calls but not across
        # presenter recreation (which is what we want on hot-reload).
        self._cv_snapshots: dict[str, dict] = {}
        # Active drag session — None outside of slider press/release.
        self._scale_drag_session = None  # type: ignore[assignment]
        # Slider value at the last apply tick. Snapshot of "from where" for
        # the next incremental factor.
        # Slider neutral is 0% (= no change); a slider value ``v`` maps to a
        # scale factor of ``1 + v/100`` relative to the size at drag start.
        self._scale_drag_last: int = 0
        # Re-entrance guard for the outliner↔image cross-mirror selection.
        self._syncing: bool = False

    # ------------------------------------------------------------------
    # Replace
    # ------------------------------------------------------------------

    def replace_control_shape(
        self,
        shape: dict,
        replace_name: bool = False,
        replace_color: bool = True,
    ) -> int:
        """Replace the shape of every selected Maya control. Returns the
        number of controls actually replaced (0 if nothing selected)."""
        from app.core.operations import replace_controls_in_selection

        return replace_controls_in_selection(
            shape,
            replace_name=replace_name,
            replace_color=replace_color,
        )

    # ------------------------------------------------------------------
    # Rotate
    # ------------------------------------------------------------------

    def rotate_cvs(self, axis: str, degrees: float) -> int:
        from app.core.operations import rotate_selected_cvs

        return rotate_selected_cvs(axis, degrees)

    # ------------------------------------------------------------------
    # Mirror
    # ------------------------------------------------------------------

    def mirror_controls(self, axis: str = "x") -> tuple[int, int, int]:
        """Mirror selected controls across ``axis``. Returns
        ``(mirrored, flipped, skipped)`` — see ``mirror_selected_controls``."""
        from app.core.operations import mirror_selected_controls

        return mirror_selected_controls(axis)

    # ------------------------------------------------------------------
    # Viewport control colour
    # ------------------------------------------------------------------

    def set_viewport_color(self, rgb: tuple) -> int:
        """Apply an override colour to every selected viewport control.
        Returns the number of controls recoloured."""
        from app.core.operations import set_selected_controls_color

        return set_selected_controls_color(rgb)

    def reset_viewport_color(self) -> int:
        """Clear the colour override on every selected viewport control.
        Returns the number of controls reset."""
        from app.core.operations import reset_selected_controls_color

        return reset_selected_controls_color()

    # ------------------------------------------------------------------
    # Scale — drag session lifecycle
    # ------------------------------------------------------------------

    def scale_drag_start(
        self,
        slider_value: int,
        axes: str = "xyz",
        from_center: bool = False,
    ) -> None:
        """Open a drag session. Captures CV snapshots for the current
        Maya selection if not already captured.

        ``axes`` selects which object-space axes the drag scales (default
        ``"xyz"`` = uniform); pass a subset like ``"xz"`` to gate axes.
        ``from_center`` pivots each control on its own CV centroid.
        """
        from app.core.operations import (
            ScaleDragSession,
            ensure_snapshots_for_selection,
        )

        ensure_snapshots_for_selection(self._cv_snapshots)
        self._scale_drag_last = slider_value
        self._scale_drag_session = ScaleDragSession.start(
            axes=axes, from_center=from_center,
        )

    def scale_drag_apply(self, slider_value: int) -> None:
        """Apply the incremental factor between ``_scale_drag_last`` and the
        new slider value. No-op outside an active drag.

        Slider values are percentage *deltas* (0 = no change), so the factor
        at value ``v`` is ``1 + v/100`` and the incremental step between two
        ticks is the ratio of those factors.
        """
        if self._scale_drag_session is None:
            return
        prev_factor = 1.0 + self._scale_drag_last / 100.0
        new_factor = 1.0 + slider_value / 100.0
        if prev_factor <= 0 or abs(new_factor - prev_factor) < 1e-9:
            return
        self._scale_drag_session.apply(new_factor / prev_factor)
        self._scale_drag_last = slider_value

    def scale_drag_end(self) -> None:
        """Close the active drag session (if any) and clear state."""
        if self._scale_drag_session is not None:
            self._scale_drag_session.end()
        self._scale_drag_session = None
        self._scale_drag_last = 0

    # ------------------------------------------------------------------
    # Scale — manual + reset
    # ------------------------------------------------------------------

    def scale_apply_manual(
        self,
        percent: int,
        axes: str = "xyz",
        from_center: bool = False,
    ) -> int:
        """Apply a single scale by ``percent`` *delta* (0 = no change, so the
        factor is ``1 + percent/100``). Returns the number of controls scaled
        — 0 for no selection, no change, or an invalid (<= -100%) factor.

        ``axes`` selects which object-space axes are scaled (default
        ``"xyz"`` = uniform); pass a subset like ``"xz"`` to gate axes.
        ``from_center`` pivots each control on its own CV centroid.
        """
        from app.core.operations import (
            ensure_snapshots_for_selection,
            scale_selected_cvs,
        )

        factor = 1.0 + percent / 100.0
        if percent == 0 or factor <= 0:
            return 0
        ensure_snapshots_for_selection(self._cv_snapshots)
        return scale_selected_cvs(factor, axes=axes, from_center=from_center)

    def scale_reset(self, axes: str = "xyz") -> int:
        """Restore selected controls to their captured CV positions.

        ``axes`` ``"xyz"`` restores all axes; pass a subset like ``"xz"`` to
        restore only those object-space components. Returns the number of
        nodes restored (0 if no snapshots).
        """
        from app.core.operations import reset_selected_cvs

        return reset_selected_cvs(self._cv_snapshots, axes=axes)

    @property
    def has_scale_snapshots(self) -> bool:
        """Read-only — useful for tests and view diagnostics."""
        return bool(self._cv_snapshots)

    # ------------------------------------------------------------------
    # Drag-and-drop into the Maya viewport
    # ------------------------------------------------------------------

    def create_controls_from_drop(self, shapes: list[dict]) -> list:
        """Create one control per shape at the world origin. Returns the
        list of created transform names (empty if ``shapes`` is empty)."""
        from app.core.operations import drop_controls_at_origin

        if not shapes:
            return []
        return drop_controls_at_origin(shapes)

    # ------------------------------------------------------------------
    # Selection mirror — re-entrance guard
    # ------------------------------------------------------------------

    def selection_sync(self) -> _SelectionSyncCtx:
        """Return a context manager that yields True the first time it is
        entered and False on any re-entrant call. Use to guard the
        outliner↔image-grid mirror handlers."""
        return _SelectionSyncCtx(self)

    # ------------------------------------------------------------------
    # Library lifecycle (DB import) — broadcast to view
    # ------------------------------------------------------------------

    def import_database(self, src_path: str) -> None:
        """Replace the SQLite library file and emit ``library_replaced`` so
        the view can re-render outliner + grid in one place."""
        self._svc.import_database(src_path)
        self.library_replaced.emit()

    # ------------------------------------------------------------------
    # Scene snapshot (save / load all scene controls to a JSON file)
    # ------------------------------------------------------------------

    def save_scene_snapshot(self, dest_path: str):
        """Serialize every curve control in the current Maya scene to JSON.

        Returns the ``SaveResult`` from ``scene_snapshot.save_scene_snapshot``
        so the view can show a result message. Imports lazily — the module
        touches ``maya.cmds`` at import time and must not load in tests
        that don't need it.
        """
        from app.core.scene_snapshot import save_scene_snapshot
        return save_scene_snapshot(dest_path)

    def load_scene_snapshot(self, src_path: str):
        """Restore controls from a snapshot file. Returns ``LoadResult``."""
        from app.core.scene_snapshot import load_scene_snapshot
        return load_scene_snapshot(src_path)
