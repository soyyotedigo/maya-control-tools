"""
Main window — wires together the outliner, image grid, toolbar, and Maya ops.
"""

import os

from app.compat import QtCore, QtGui, QtWidgets
from app.config import (
    VERSION,
    WINDOW_TITLE,
    AUTHOR,
    SETTINGS_KEY,
    MIN_WIDTH,
    MIN_HEIGHT,
    ICONS_DIR,
)
from app.core.control_creation import (
    create_shapes_from_selection,
    resolve_control_selection,
    unique_shape_identity,
)
from app.core.shape_data import decode_color
from app.core.shape_service import ShapeService
from app.logger import log
from app.presenters.control_presenter import ControlPresenter
from app.views.groups_view import OutlinerWidget
from app.views.images_view import ImageView
from app.views.maya_integration import (
    install_viewport_drop,
    maya_main_window,
    show_as_workspace_control,  # re-exported for main.py / install.py / userSetup.py
)
from app.views.widgets import ColorSwatch


class _JumpToClickSlider(QtWidgets.QSlider):
    """QSlider where a click on the groove triggers a one-shot scale to
    that value (press → setValue → release in sequence). Dragging the
    handle is unchanged. Default QSlider would step by pageStep — here
    we want the click to land exactly on the clicked position."""

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(
                QtWidgets.QStyle.CC_Slider,
                opt,
                QtWidgets.QStyle.SC_SliderHandle,
                self,
            )
            if not handle.contains(event.pos()):
                if self.orientation() == QtCore.Qt.Horizontal:
                    pos, length = event.pos().x(), self.width()
                else:
                    pos, length = event.pos().y(), self.height()
                value = QtWidgets.QStyle.sliderValueFromPosition(
                    self.minimum(),
                    self.maximum(),
                    pos,
                    length,
                    opt.upsideDown,
                )
                # Synthesize a quick press→value→release so the existing
                # drag-session pipeline (open undo, apply, snap to 100)
                # runs as if the user did a tiny drag to ``value``.
                self.sliderPressed.emit()
                self.setValue(value)
                self.sliderReleased.emit()
                event.accept()
                return
        super().mousePressEvent(event)


class ControlMe(QtWidgets.QWidget):
    """Main ControlMe window — works inside Maya or standalone."""

    def __init__(self, parent=None, docked=False, service=None):
        log.info("ControlMe.__init__ starting (docked=%s)", docked)
        try:
            super().__init__(parent or maya_main_window())
            self.setWindowTitle(f"{WINDOW_TITLE}  v{VERSION}")
            self.setWindowIcon(QtGui.QIcon(str(ICONS_DIR / "controls_tool.png")))
            # When docked inside a workspaceControl the Qt.Window flag must be
            # absent — the workspace panel is already a proper window.
            if not docked:
                self.setWindowFlags(QtCore.Qt.Window)
            self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

            self._settings = QtCore.QSettings(AUTHOR, SETTINGS_KEY)
            self._svc = service if service is not None else ShapeService()

            # The presenter owns Maya orchestration + transient state
            # (CV snapshots, drag session, selection-sync guard). The view
            # only renders state and forwards user gestures to it.
            self._presenter = ControlPresenter(self._svc, parent=self)
            self._presenter.library_replaced.connect(self._load_shapes)

            self._svc.initialize()
            self._svc.seed_builtins()

            self.create_widgets()
            self.create_layout()
            self.create_connections()
            self._load_shapes()
            self._restore_settings()
            self._setup_viewport_drop()

            from app.styles import load_stylesheet

            self.setStyleSheet(load_stylesheet())

            log.info("ControlMe.__init__ complete — v%s", VERSION)
        except Exception:
            log.exception("ControlMe.__init__ FAILED — window may not appear")
            raise

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def create_widgets(self):
        # ── Menu bar ──────────────────────────────────────────────────────
        self.menu_bar = QtWidgets.QMenuBar()

        file_menu = self.menu_bar.addMenu("File")
        self.export_db_action = file_menu.addAction("Export Database…")
        self.import_db_action = file_menu.addAction("Import Database…")

        help_menu = self.menu_bar.addMenu("Help")
        self.open_log_action = help_menu.addAction("Open Log File")
        help_menu.addSeparator()
        self.about_action = help_menu.addAction("About")

        # ── Rest of widgets ───────────────────────────────────────────────
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        self.outliner = OutlinerWidget()
        self.image_view = ImageView()

        # Toolbar buttons
        self.create_ctrl_btn = QtWidgets.QPushButton("Create Control")
        self.create_ctrl_btn.setIcon(QtGui.QIcon(str(ICONS_DIR / "create_control.png")))
        self.create_ctrl_btn.setToolTip(
            "Create a new control shape from selected edges in Maya"
        )

        self.replace_ctrl_btn = QtWidgets.QPushButton("Replace Control")
        self.replace_ctrl_btn.setIcon(QtGui.QIcon(str(ICONS_DIR / "replace_control.png")))
        self.replace_ctrl_btn.setToolTip(
            "Replace the shape of the selected Maya control, preserving its current size"
        )

        # Orientation rotate buttons (CV rotation in object space, 90° per click)
        _rot_tip = (
            "Rotate the selected Maya control's curve CVs 90° around the {ax} axis.\n"
            "Each click adds 90°. Works in object space — pivot and connections untouched.\n"
            "Left-click: +90°  |  Right-click: -90°"
        )
        self.rot_x_btn = QtWidgets.QPushButton("X")
        self.rot_y_btn = QtWidgets.QPushButton("Y")
        self.rot_z_btn = QtWidgets.QPushButton("Z")
        for btn, ax in [
            (self.rot_x_btn, "X"),
            (self.rot_y_btn, "Y"),
            (self.rot_z_btn, "Z"),
        ]:
            btn.setFixedSize(26, 24)
            btn.setToolTip(_rot_tip.format(ax=ax))
            btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        # Scale controls — horizontal slider + spinbox in the Settings panel.
        # Slider applies CV-scale live during drag (one undo chunk per gesture)
        # and snaps back to 100% on release. Spinbox accepts a manual % and
        # applies on Enter, then also snaps back to 100%.
        self.scale_slider = _JumpToClickSlider(QtCore.Qt.Horizontal)
        self.scale_slider.setRange(10, 300)
        self.scale_slider.setValue(100)
        self.scale_slider.setTickPosition(QtWidgets.QSlider.NoTicks)
        self.scale_slider.setSingleStep(1)
        self.scale_slider.setPageStep(20)
        self.scale_slider.setToolTip(
            "Drag to scale selected controls live (one Ctrl+Z per drag).\n"
            "Click on the track for a quick one-shot scale to that value.\n"
            "Releases snap back to 100%. Range: 10%–300%."
        )

        self.scale_spin = QtWidgets.QSpinBox()
        self.scale_spin.setRange(1, 10000)
        self.scale_spin.setValue(100)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setAlignment(QtCore.Qt.AlignCenter)
        self.scale_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.scale_spin.setFixedWidth(64)
        self.scale_spin.setToolTip(
            "Type a percentage and press Enter to scale by that amount.\n"
            "100% = no change. After applying, the field snaps back to 100%."
        )

        self.scale_reset_btn = QtWidgets.QPushButton("R")
        self.scale_reset_btn.setFixedSize(26, 24)
        self.scale_reset_btn.setToolTip(
            "Reset selected controls to their original CV size.\n"
            "Original positions are captured the first time you scale a control."
        )

        # Replace-on-apply checkboxes — stored in QSettings so they survive
        # across sessions. Shared icon size keeps the column visually aligned.
        _cb_icon_size = QtCore.QSize(18, 18)

        self.replace_name_cb = QtWidgets.QCheckBox("Replace name")
        self.replace_name_cb.setIcon(QtGui.QIcon(str(ICONS_DIR / "replace_name_control.png")))
        self.replace_name_cb.setIconSize(_cb_icon_size)
        self.replace_name_cb.setToolTip(
            "When replacing a control, rename the Maya transform to match\n"
            "the library shape label."
        )
        self.replace_color_cb = QtWidgets.QCheckBox("Replace color")
        self.replace_color_cb.setIcon(QtGui.QIcon(str(ICONS_DIR / "replace_control_color.png")))
        self.replace_color_cb.setIconSize(_cb_icon_size)
        self.replace_color_cb.setChecked(True)
        self.replace_color_cb.setToolTip(
            "When checked, apply the library shape's color to the replaced\n"
            "control. When unchecked, the original scene color is preserved."
        )

        # Optional mGear integration: after replacing the control, run mGear's
        # "Extract Controls" so the matching guide stores the new shape and
        # the next rig rebuild picks it up. Disabled when mGear isn't found.
        from app.core.mgear_integration import is_available as _mgear_available
        self.extract_mgear_cb = QtWidgets.QCheckBox("Extract to mgear")
        self.extract_mgear_cb.setIcon(QtGui.QIcon(str(ICONS_DIR / "replace_mgear_control.png")))
        self.extract_mgear_cb.setIconSize(_cb_icon_size)
        _mgear_tooltip = (
            "After replacing the control, run mGear's 'Extract Controls' so\n"
            "the matching guide is updated with the new shape. The next rig\n"
            "rebuild will pick it up automatically.\n\n"
            "Requires mGear Framework to be installed."
        )
        if _mgear_available():
            self.extract_mgear_cb.setToolTip(_mgear_tooltip)
        else:
            self.extract_mgear_cb.setEnabled(False)
            self.extract_mgear_cb.setChecked(False)
            self.extract_mgear_cb.setToolTip(
                _mgear_tooltip
                + "\n\nDisabled: mGear was not found on the Python path."
            )

        # Control Settings group — scale row + replace-options row.
        self.settings_group = QtWidgets.QGroupBox("Control Settings")
        settings_layout = QtWidgets.QVBoxLayout(self.settings_group)
        settings_layout.setContentsMargins(8, 4, 8, 6)
        settings_layout.setSpacing(4)

        scale_row = QtWidgets.QHBoxLayout()
        scale_row.setSpacing(6)
        scale_row.addWidget(QtWidgets.QLabel("Scale"))
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_spin)
        scale_row.addWidget(self.scale_reset_btn)

        # Vertical stack: header row + one row per option (checkbox on the
        # left, detailed description on the right). Description column
        # stretches so it wraps to available width.
        replace_grid = QtWidgets.QGridLayout()
        replace_grid.setHorizontalSpacing(12)
        replace_grid.setVerticalSpacing(4)
        replace_grid.setColumnStretch(1, 1)

        header = QtWidgets.QLabel("When replacing a control:")
        header_font = header.font()
        header_font.setBold(True)
        header.setFont(header_font)
        replace_grid.addWidget(header, 0, 0, 1, 2)

        for row, (cb, descr) in enumerate([
            (
                self.replace_name_cb,
                "Rename the Maya transform to match the library shape's label.",
            ),
            (
                self.replace_color_cb,
                "Apply the library shape's color. Unchecked: keep the current scene color.",
            ),
            (
                self.extract_mgear_cb,
                "After replacing, run mGear's Extract Controls so the matching guide is updated.",
            ),
        ], start=1):
            replace_grid.addWidget(cb, row, 0)
            descr_label = QtWidgets.QLabel(descr)
            descr_label.setWordWrap(True)
            descr_label.setEnabled(cb.isEnabled())
            replace_grid.addWidget(descr_label, row, 1)

        settings_layout.addLayout(scale_row)
        settings_layout.addLayout(replace_grid)

        # Right pane container: previews on top, scale panel flush below.
        # Plain VBox (no splitter) so the bottom group always hugs the
        # preview — no draggable handle and no stale persisted sizes.
        self.right_pane = QtWidgets.QWidget()

        self.duplicate_btn = QtWidgets.QPushButton("Duplicate")
        self.duplicate_btn.setIcon(QtGui.QIcon(str(ICONS_DIR / "duplicate_control.png")))
        self.duplicate_btn.setToolTip("Duplicate selected shape")
        self.remove_btn = QtWidgets.QPushButton("Remove")
        self.remove_btn.setIcon(QtGui.QIcon(str(ICONS_DIR / "remove_control.png")))
        self.remove_btn.setToolTip("Delete selected shape from library")

        # Buttons whose label is dropped to icon-only when the window is narrow.
        # See resizeEvent / _apply_toolbar_density.
        self._collapsible_btns = [
            (self.create_ctrl_btn, "Create Control"),
            (self.replace_ctrl_btn, "Replace Control"),
            (self.duplicate_btn, "Duplicate"),
            (self.remove_btn, "Remove"),
        ]
        self._toolbar_collapsed = False

        self.color_swatch = ColorSwatch()
        self.color_swatch.setToolTip("Set control color")
        # Compact "R" reset button — matches scale_reset_btn so the two
        # reset affordances look and behave consistently in the toolbar.
        self.reset_color_btn = QtWidgets.QPushButton("R")
        self.reset_color_btn.setFixedSize(26, 24)
        self.reset_color_btn.setToolTip("Reset selected controls to their original color.")

    def create_layout(self):
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(self.create_ctrl_btn)
        toolbar.addWidget(self.replace_ctrl_btn)
        toolbar.addSpacing(6)
        toolbar.addWidget(QtWidgets.QLabel("Orient:"))
        toolbar.addWidget(self.rot_x_btn)
        toolbar.addWidget(self.rot_y_btn)
        toolbar.addWidget(self.rot_z_btn)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.duplicate_btn)
        toolbar.addWidget(self.remove_btn)
        toolbar.addSpacing(16)
        toolbar.addWidget(QtWidgets.QLabel("Color:"))
        toolbar.addWidget(self.color_swatch)
        toolbar.addWidget(self.reset_color_btn)
        toolbar.addStretch()

        # Right pane: preview grid on top, scale panel flush below.
        right_layout = QtWidgets.QVBoxLayout(self.right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self.image_view, 1)
        right_layout.addWidget(self.settings_group, 0)

        self.splitter.addWidget(self.outliner)
        self.splitter.addWidget(self.right_pane)
        self.splitter.setSizes([150, 350])

        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(6, 6, 6, 6)
        main.setSpacing(4)
        main.setMenuBar(self.menu_bar)
        main.addLayout(toolbar)
        main.addWidget(self.splitter)

    def create_connections(self):
        # Sync full multi-selection between outliner and image grid
        self.image_view.list_widget.itemSelectionChanged.connect(
            self._sync_outliner_from_image_selection
        )
        self.outliner.list_widget.itemSelectionChanged.connect(
            self._sync_image_from_outliner_selection
        )

        # Create Control from edge selection
        self.create_ctrl_btn.clicked.connect(self._create_control_from_selection)

        # Replace Control in Maya viewport (button, context menus, double-click)
        self.replace_ctrl_btn.clicked.connect(self._replace_control_in_viewport)
        self.outliner.replace_action.triggered.connect(
            self._replace_control_in_viewport
        )
        self.image_view.replace_action.triggered.connect(
            self._replace_control_in_viewport
        )
        self.outliner.apply_requested.connect(self._replace_control_in_viewport)
        self.image_view.apply_requested.connect(self._replace_control_in_viewport)
        self.outliner.search_changed.connect(self.image_view.apply_filter)

        # Duplicate from context menus and toolbar
        self.outliner.duplicate_action.triggered.connect(self._duplicate_shape)
        self.image_view.duplicate_action.triggered.connect(self._duplicate_shape)
        self.duplicate_btn.clicked.connect(self._duplicate_shape)

        # Remove from context menus and toolbar
        self.outliner.remove_action.triggered.connect(self._delete_shape)
        self.image_view.remove_action.triggered.connect(self._delete_shape)
        self.remove_btn.clicked.connect(self._delete_shape)

        # Reset color from context menus
        self.outliner.reset_color_action.triggered.connect(self._reset_color)
        self.image_view.reset_color_action.triggered.connect(self._reset_color)

        # Rename
        self.image_view.shape_renamed.connect(self._rename_shape)
        self.outliner.shape_renamed.connect(self._rename_shape)

        # Orientation rotate (left-click +90°, right-click -90°)
        self.rot_x_btn.clicked.connect(lambda: self._rotate_cvs("x", 90))
        self.rot_y_btn.clicked.connect(lambda: self._rotate_cvs("y", 90))
        self.rot_z_btn.clicked.connect(lambda: self._rotate_cvs("z", 90))
        self.rot_x_btn.customContextMenuRequested.connect(
            lambda _: self._rotate_cvs("x", -90)
        )
        self.rot_y_btn.customContextMenuRequested.connect(
            lambda _: self._rotate_cvs("y", -90)
        )
        self.rot_z_btn.customContextMenuRequested.connect(
            lambda _: self._rotate_cvs("z", -90)
        )

        # Scale controls (CV-level scale of selected Maya controls)
        # Slider: pressed → open undo chunk, valueChanged → apply incremental
        # factor, released → close chunk + snap back to 100%.
        self.scale_slider.sliderPressed.connect(self._scale_slider_pressed)
        self.scale_slider.valueChanged.connect(self._scale_slider_changed)
        self.scale_slider.sliderReleased.connect(self._scale_slider_released)
        # returnPressed (not editingFinished) so focus loss does not apply.
        self.scale_spin.lineEdit().returnPressed.connect(self._scale_apply_manual)
        self.scale_reset_btn.clicked.connect(self._scale_reset)

        # Color
        self.image_view.color_picked.connect(self._set_color)
        self.color_swatch.color_changed.connect(self._set_color)
        self.reset_color_btn.clicked.connect(self._reset_color)

        # Menu bar
        self.export_db_action.triggered.connect(self._export_db)
        self.import_db_action.triggered.connect(self._import_db)
        self.open_log_action.triggered.connect(self._open_log)
        self.about_action.triggered.connect(self._show_about)

        # Persist settings immediately — closeEvent may not fire in Maya
        # workspace control mode when the panel is hidden/closed.
        self.image_view.size_slider.valueChanged.connect(self._save_settings)
        self.image_view.projection_combo.currentTextChanged.connect(self._save_settings)
        self.replace_name_cb.toggled.connect(self._save_settings)
        self.replace_color_cb.toggled.connect(self._save_settings)
        self.extract_mgear_cb.toggled.connect(self._save_settings)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_shapes(self) -> None:
        """Load all shapes from the database and populate both panels."""
        self._shape_labels = self._svc.get_shape_labels()  # {name: label}
        all_shapes = self._svc.list_shapes()  # full shape dicts
        self.outliner.populate(self._shape_labels)
        self.image_view.populate(all_shapes)

    def _current_key(self) -> str | None:
        return self.image_view.selected_key() or self.outliner.selected_key()

    def _selected_keys(self) -> list:
        """Return all selected shape keys from image view or outliner."""
        keys = self.image_view.selected_keys()
        if not keys:
            keys = self.outliner.selected_keys()
        return keys

    def _insert_shape_ui(self, key: str, label: str) -> None:
        """Insert one shape into both UI panels and local labels cache."""
        shape = self._svc.get_shape(key)
        if not shape:
            return
        self._shape_labels[key] = label
        self.image_view.add_shape_item(shape)
        self.outliner.add_shape_item(key, label)

    def _sync_outliner_from_image_selection(self) -> None:
        """Mirror the image grid's full selection → outliner. Ctrl+click safe."""
        with self._presenter.selection_sync() as acquired:
            if not acquired:
                return
            self._mirror_selection(
                source=self.image_view, target=self.outliner
            )

    def _sync_image_from_outliner_selection(self) -> None:
        """Mirror the outliner's full selection → image grid. Ctrl+click safe."""
        with self._presenter.selection_sync() as acquired:
            if not acquired:
                return
            self._mirror_selection(
                source=self.outliner, target=self.image_view
            )

    def _mirror_selection(self, source, target) -> None:
        """Shared mirror logic: copy ``source``'s selection into ``target``."""
        keys = set(source.selected_keys())
        current_key = source.selected_key()
        lw = target.list_widget
        lw.clearSelection()
        for i in range(lw.count()):
            item = lw.item(i)
            if not item:
                continue
            k = item.data(QtCore.Qt.UserRole)
            if k in keys:
                item.setSelected(True)
            if k == current_key:
                lw.setCurrentItem(item, QtCore.QItemSelectionModel.NoUpdate)
        if current_key:
            self._update_color_swatch(current_key)

    def _update_color_swatch(self, key: str) -> None:
        """Sync the toolbar color swatch to the selected shape's stored color."""
        shape = self._svc.get_shape(key)
        color = decode_color(shape.get("color")) if shape else None
        self.color_swatch.set_color(color if color else (1.0, 1.0, 1.0))

    def _update_color_swatch_from_selection(self) -> None:
        """Refresh the color swatch from the current selection (handles Ctrl+click)."""
        key = self._current_key()
        if key:
            self._update_color_swatch(key)

    # ------------------------------------------------------------------
    # Shape operations
    # ------------------------------------------------------------------

    def _duplicate_shape(self) -> None:
        """Duplicate all selected shapes with granular UI update."""
        keys = self._selected_keys()
        if not keys:
            return
        for key in keys:
            new_name = self._svc.duplicate_shape(key)
            if new_name:
                shape = self._svc.get_shape(new_name)
                if shape:
                    self._insert_shape_ui(new_name, shape["label"])

    def _rename_shape(self, old_key: str, new_label: str) -> None:
        """Rename a shape in the database and update views in-place."""
        new_key = self._svc.rename_shape(old_key, new_label)
        self._shape_labels.pop(old_key, None)
        self._shape_labels[new_key] = new_label
        self.image_view.rename_shape_item(old_key, new_key, new_label)
        self.outliner.rename_shape_item(old_key, new_key, new_label)

    def _delete_shape(self) -> None:
        """Delete all selected shapes from the database."""
        keys = self._selected_keys()
        if not keys:
            return
        count = len(keys)
        if count == 1:
            label = self._shape_labels.get(keys[0], keys[0])
            msg = f'Remove "{label}" from the library?'
        else:
            msg = f"Remove {count} shapes from the library?"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Remove shape",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        for key in keys:
            self._svc.delete_shape(key)
            self._shape_labels.pop(key, None)
        self.image_view.remove_shape_items(keys)
        self.outliner.remove_shape_items(keys)

    def _set_color(self, rgb: tuple) -> None:
        keys = self._selected_keys()
        if not keys:
            return
        for key in keys:
            self._svc.update_color(key, rgb)
            self.image_view.update_shape_color(key, rgb)

    def _reset_color(self) -> None:
        keys = self._selected_keys()
        if not keys:
            return
        for key in keys:
            self._svc.update_color(key, None)
            self.image_view.update_shape_color(key, None)

    # ------------------------------------------------------------------
    # Create Control from Maya edge selection
    # ------------------------------------------------------------------

    def _create_control_from_selection(self) -> None:
        """Convert the current Maya selection into a new library control shape.

        Accepts NURBS curve transforms (captured directly), or mesh edges /
        faces / vertices / whole objects (converted via edge-to-curve).
        Wraps all Maya calls in a single undo chunk.
        """
        selection = resolve_control_selection()
        if selection.kind == "invalid":
            QtWidgets.QMessageBox.warning(
                self, "No Valid Selection", selection.error or ""
            )
            return

        label, ok = QtWidgets.QInputDialog.getText(
            self, "Create Control", "Control name:", text="my_control"
        )
        if not ok or not label.strip():
            return

        existing = {s["name"] for s in self._svc.list_shapes()}
        key, clean_label = unique_shape_identity(label, existing)

        result = create_shapes_from_selection(selection)
        if not result.ok:
            QtWidgets.QMessageBox.critical(
                self,
                "Conversion Failed",
                result.error or "Could not create control from selection.",
            )
            return

        self._svc.save_shape(
            name=key, label=clean_label, shapes_data=result.shapes_data
        )
        self._insert_shape_ui(key, clean_label)

    # ------------------------------------------------------------------
    # Replace Control in Maya viewport
    # ------------------------------------------------------------------

    def _replace_control_in_viewport(self) -> None:
        """Swap the curve shape of every selected Maya control with the
        currently selected library shape, preserving size and orientation.
        """
        key = self._current_key()
        if not key:
            QtWidgets.QMessageBox.warning(
                self, "Replace Control", "Select a shape in the library first."
            )
            return

        shape = self._svc.get_shape(key)
        if not shape:
            return

        if self._presenter.replace_control_shape(
            shape,
            replace_name=self.replace_name_cb.isChecked(),
            replace_color=self.replace_color_cb.isChecked(),
            extract_to_mgear=self.extract_mgear_cb.isChecked(),
        ) == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "Replace Control",
                "Select one or more controls in the Maya viewport first.",
            )

    # ------------------------------------------------------------------
    # Orientation helpers
    # ------------------------------------------------------------------

    def _rotate_cvs(self, axis: str, degrees: float) -> None:
        """Rotate the CVs of every selected Maya control by *degrees* around *axis*.

        Left-click the X / Y / Z buttons for +90°, right-click for -90°.
        Each click is its own undo chunk, so Ctrl+Z undoes one step at a time.
        """
        if self._presenter.rotate_cvs(axis, degrees) == 0:
            log.debug("_rotate_cvs: nothing selected")

    # ------------------------------------------------------------------
    # Scale — CV-level scale of selected Maya controls
    # ------------------------------------------------------------------

    def _scale_slider_pressed(self) -> None:
        """Start a slider-drag gesture. Opens one undo chunk for the gesture."""
        # If the snap-back animation is still running from a previous gesture,
        # cancel it and silently reset to 100 so the new gesture starts from
        # a clean baseline (scale_drag_start records the starting value).
        anim = getattr(self, "_scale_snap_anim", None)
        if anim is not None and anim.state() == QtCore.QAbstractAnimation.Running:
            anim.stop()
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(100)
            self.scale_slider.blockSignals(False)
        value = self.scale_slider.value()
        self._presenter.scale_drag_start(value)
        # Mirror the slider value into the spinbox during drag (read-only feel).
        self._sync_spin_to_slider(value)

    def _scale_slider_changed(self, value: int) -> None:
        """Apply the incremental factor between the previous and current slider value."""
        self._presenter.scale_drag_apply(value)
        self._sync_spin_to_slider(value)

    def _scale_slider_released(self) -> None:
        """End drag: close undo chunk and snap slider + spinbox back to 100%."""
        self._presenter.scale_drag_end()
        self._snap_scale_to_100()

    def _sync_spin_to_slider(self, value: int) -> None:
        """Update the spinbox display without triggering its handler."""
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(value)
        self.scale_spin.blockSignals(False)

    def _snap_scale_to_100(self) -> None:
        """Animate slider + spinbox back to 100% so the user sees the reset.

        The drag session is already closed by ``scale_drag_end`` before this
        runs, so the valueChanged signals fired during the animation are
        no-ops in scale_drag_apply (early return when session is None).
        """
        current = self.scale_slider.value()
        if current == 100:
            self._sync_spin_to_slider(100)
            return
        anim = getattr(self, "_scale_snap_anim", None)
        if anim is not None:
            anim.stop()
        anim = QtCore.QPropertyAnimation(self.scale_slider, b"value", self)
        anim.setDuration(180)
        anim.setStartValue(current)
        anim.setEndValue(100)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.start()
        self._scale_snap_anim = anim

    def _scale_apply_manual(self) -> None:
        """Apply the spinbox percentage as a scale factor, then reset to 100."""
        self._presenter.scale_apply_manual(self.scale_spin.value())
        self._sync_spin_to_slider(100)

    def _scale_reset(self) -> None:
        """Restore selected controls to their original (pre-scale) CV positions."""
        self._presenter.scale_reset()
        self._snap_scale_to_100()

    # ------------------------------------------------------------------
    # Viewport drag-and-drop
    # ------------------------------------------------------------------

    def _setup_viewport_drop(self) -> None:
        """Install a drop event filter on every Maya model panel viewport.

        No-op when running outside Maya.
        """
        self._drop_filter = install_viewport_drop(
            self, self._create_control_from_drop
        )

    def _create_control_from_drop(self, payload: str) -> None:
        """Create one control per dragged shape key at world origin (0, 0, 0).

        ``payload`` is a newline-separated list of shape keys — one key
        when a single item was dragged, multiple when several were selected.
        """
        keys = [k for k in payload.split("\n") if k]
        if not keys:
            return
        shapes = [self._svc.get_shape(k) for k in keys]
        shapes = [s for s in shapes if s]
        self._presenter.create_controls_from_drop(shapes)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _export_db(self) -> None:
        dest, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Database", "controlme.db", "SQLite Database (*.db)"
        )
        if not dest:
            return
        try:
            self._svc.export_database(dest)
            log.info("DB exported to: %s", dest)
            QtWidgets.QMessageBox.information(
                self, "Export Database", f"Database exported to:\n{dest}"
            )
        except Exception as exc:
            log.exception("DB export failed")
            QtWidgets.QMessageBox.critical(self, "Export Failed", str(exc))

    def _import_db(self) -> None:
        src, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import Database", "", "SQLite Database (*.db)"
        )
        if not src:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Import Database",
            "This will replace your current library with the imported database.\n"
            "Are you sure?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._presenter.import_database(src)  # also emits library_replaced → _load_shapes
            log.info("DB imported from: %s", src)
            QtWidgets.QMessageBox.information(
                self, "Import Database", "Database imported successfully."
            )
        except Exception as exc:
            log.exception("DB import failed")
            QtWidgets.QMessageBox.critical(self, "Import Failed", str(exc))

    def _open_log(self) -> None:
        import subprocess
        import sys
        from app.paths import get_log_path

        path = get_log_path()
        # Create the file if it doesn't exist yet so the OS can open it.
        if not os.path.exists(path):
            open(path, "a").close()
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            log.exception("Could not open log file")
            QtWidgets.QMessageBox.critical(self, "Open Log", str(exc))

    def _show_about(self) -> None:
        from app.paths import get_db_path, get_log_path

        QtWidgets.QMessageBox.about(
            self,
            f"About {WINDOW_TITLE}",
            f"<b>{WINDOW_TITLE}</b><br>"
            f"Version: {VERSION}<br>"
            f"Author: {AUTHOR}<br><br>"
            f"<b>Database:</b><br>{get_db_path()}<br><br>"
            f"<b>Log file:</b><br>{get_log_path()}",
        )

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _restore_settings(self) -> None:
        geo = self._settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        splitter = self._settings.value("splitter")
        if splitter is not None:
            self.splitter.restoreState(splitter)
        # Block signals while restoring so that valueChanged / currentTextChanged
        # do NOT fire _save_settings before the window has been shown.
        # Calling saveGeometry() from inside __init__ (before show()) returns
        # invalid data and would overwrite the correct saved geometry.
        thumb_size = self._settings.value("thumb_size")
        if thumb_size is not None:
            self.image_view.size_slider.blockSignals(True)
            self.image_view.size_slider.setValue(int(thumb_size))
            self.image_view.size_slider.blockSignals(False)
            self.image_view._on_size_changed(int(thumb_size))

        projection = self._settings.value("projection")
        if projection is not None:
            self.image_view.projection_combo.blockSignals(True)
            self.image_view.projection_combo.setCurrentText(projection)
            self.image_view.projection_combo.blockSignals(False)
            self.image_view._on_projection_changed(projection)

        replace_name = self._settings.value("replace_name")
        if replace_name is not None:
            self.replace_name_cb.setChecked(replace_name == "true")
        replace_color = self._settings.value("replace_color")
        if replace_color is not None:
            self.replace_color_cb.setChecked(replace_color == "true")
        extract_to_mgear = self._settings.value("extract_to_mgear")
        # Only restore when the checkbox is currently enabled (mGear was
        # detected). If mGear is not installed on this machine, a previously
        # saved "true" must not re-enable the disabled checkbox.
        if extract_to_mgear is not None and self.extract_mgear_cb.isEnabled():
            self.extract_mgear_cb.setChecked(extract_to_mgear == "true")

    def _save_settings(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("splitter", self.splitter.saveState())
        self._settings.setValue("thumb_size", self.image_view.size_slider.value())
        self._settings.setValue(
            "projection", self.image_view.projection_combo.currentText()
        )
        self._settings.setValue("replace_name", str(self.replace_name_cb.isChecked()).lower())
        self._settings.setValue("replace_color", str(self.replace_color_cb.isChecked()).lower())
        self._settings.setValue(
            "extract_to_mgear", str(self.extract_mgear_cb.isChecked()).lower()
        )

    # Window width below which the toolbar buttons drop their labels and
    # render icon-only. Tooltips still describe each action.
    _TOOLBAR_COLLAPSE_WIDTH = 620

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_toolbar_density(self.width())

    def _apply_toolbar_density(self, width: int) -> None:
        collapsed = width < self._TOOLBAR_COLLAPSE_WIDTH
        if collapsed == self._toolbar_collapsed:
            return
        self._toolbar_collapsed = collapsed
        for btn, label in self._collapsible_btns:
            btn.setText("" if collapsed else label)

    def closeEvent(self, event) -> None:
        import traceback

        # Capture the call stack so we can see *what* triggered the close.
        stack = "".join(traceback.format_stack()[:-1])
        log.info("closeEvent triggered — saving settings\nCall stack:\n%s", stack)
        self._save_settings()
        log.info("closeEvent complete — window is closing")
        super().closeEvent(event)


# ``show_as_workspace_control`` is imported from ``app.views.maya_integration``
# at the top of this module so external callers (``main.py``, ``install.py``,
# ``userSetup.py``) can keep importing it from ``app.views.main_view``.
