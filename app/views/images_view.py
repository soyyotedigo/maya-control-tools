"""
Right panel — visual grid of control shape thumbnails.

Thumbnails are drawn procedurally with QPainter using 2D projections
of the shape CV points, so no Maya viewport or external images needed.
"""
from functools import lru_cache
import math

from app.compat import QtCore, QtGui, QtWidgets, QAction
from app.config import THUMBNAIL_CACHE_SIZE
from app.core.shape_data import decode_color, decode_cv_data, encode_color

# MIME type used for drag-and-drop from the shape grid to Maya viewport.
_MIME_TYPE = "application/x-controlme-shape"

# Preview sizes for the slider steps
IMAGE_SIZES = {0: 64, 1: 96, 2: 128, 3: 192}

# Available 2D projections for shape thumbnails.
# "Perspective" is handled specially in _project_points (isometric).
PROJECTIONS = {
    "Front":       lambda p: (p[0], p[1]),                          # XY
    "Top":         lambda p: (p[0], p[2]),                          # XZ
    "Side":        lambda p: (p[2], p[1]),                          # ZY
    "Perspective": None,                                            # isometric
}


def _isometric_project(points: list) -> list:
    """Isometric projection that works for both flat and 3D shapes.

    Applies a ~30 deg rotation around X then ~45 deg around Y so that
    all three axes are visible — even when a shape is completely flat
    on one plane.
    """
    cos30 = math.cos(math.radians(30))
    sin30 = math.sin(math.radians(30))
    cos45 = math.cos(math.radians(45))
    sin45 = math.sin(math.radians(45))

    result = []
    for p in points:
        x, y, z = p[0], p[1], p[2]
        # Rotate around X axis by 30 deg
        y1 = y * cos30 - z * sin30
        z1 = y * sin30 + z * cos30
        # Rotate around Y axis by 45 deg
        x2 = x * cos45 + z1 * sin45
        # Project to 2D: (x2, y1)
        result.append((x2, y1))
    return result


@lru_cache(maxsize=THUMBNAIL_CACHE_SIZE)
def _cached_render(cv_data_json, degree: int, size: int,
                   projection: str, color_json) -> "QtGui.QPixmap":
    """Thumbnail renderer with LRU cache keyed on content.

    All parameters must be hashable (strings, ints).  ``cv_data_json``
    and ``color_json`` are the raw DB JSON strings (or None).
    """
    cv_data = decode_cv_data(cv_data_json)
    color = decode_color(color_json)
    return _render_shape_preview(cv_data, degree, size, projection, color)


class _DraggableList(QtWidgets.QListWidget):
    """QListWidget that initiates a MIME drag encoding the shape key.

    Overrides mouse events directly so the drag works regardless of the
    Movement mode set on the list (Static prevents Qt's built-in drag).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_origin = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_origin = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & QtCore.Qt.LeftButton) or self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        dist = (event.pos() - self._drag_origin).manhattanLength()
        if dist < QtWidgets.QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        # Only drag the single item under the cursor, regardless of
        # how many items are selected. Multi-selection still works for
        # color changes, remove, etc. — but drag-and-drop creates
        # exactly one control in the Maya viewport.
        drag_item = self.itemAt(self._drag_origin)
        if not drag_item:
            return
        key = drag_item.data(QtCore.Qt.UserRole)
        if not key:
            return

        mime = QtCore.QMimeData()
        mime.setData(_MIME_TYPE, key.encode("utf-8"))

        pixmap = drag_item.icon().pixmap(64, 64)
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QtCore.QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec_(QtCore.Qt.CopyAction)
        self._drag_origin = None

        # After the drag ends Qt still thinks the mouse button is held down
        # (super().mousePressEvent was called but never got a matching release).
        # Send a synthetic release so the list view clears its rubber-band
        # / selection state, preventing a stray group-selection box when the
        # user clicks back on the UI after dropping in the Maya viewport.
        release = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            event.pos(),
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        super().mouseReleaseEvent(release)


class ImageView(QtWidgets.QWidget):
    """Icon-mode grid of shape previews with size slider and search."""

    shape_selected = QtCore.Signal(str)    # emits shape key
    shape_renamed = QtCore.Signal(str, str)  # emits (old_key, new_label)
    color_picked = QtCore.Signal(tuple)    # emits (r, g, b) float tuple

    def __init__(self, parent=None):
        super().__init__(parent)
        self._size = IMAGE_SIZES[1]
        self._projection = "Perspective"
        self._shapes: list = []  # list of shape dicts from DB

        self.create_widgets()
        self.create_layout()
        self.create_connections()

    def create_widgets(self):
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(0, 3)
        self.size_slider.setValue(1)
        self.size_slider.setTickInterval(1)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip("Thumbnail size")

        self.list_widget = _DraggableList()
        self.list_widget.setViewMode(QtWidgets.QListView.IconMode)
        self.list_widget.setIconSize(QtCore.QSize(self._size, self._size))
        self.list_widget.setGridSize(self._grid_size())
        self.list_widget.setResizeMode(QtWidgets.QListView.Adjust)
        self.list_widget.setMovement(QtWidgets.QListView.Static)
        self.list_widget.setSpacing(6)
        self.list_widget.setWordWrap(True)
        self.list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        self.projection_combo = QtWidgets.QComboBox()
        self.projection_combo.addItems(list(PROJECTIONS.keys()))
        self.projection_combo.setCurrentText("Perspective")
        self.projection_combo.setToolTip("Thumbnail projection")

        self.context_menu = QtWidgets.QMenu(self)
        self.replace_action = QAction("Replace Control", self)
        self.color_action = QAction("Color...", self)
        self.reset_color_action = QAction("Reset Color", self)
        self.duplicate_action = QAction("Duplicate", self)
        self.remove_action = QAction("Remove", self)
        self.context_menu.addAction(self.replace_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.color_action)
        self.context_menu.addAction(self.reset_color_action)
        self.context_menu.addAction(self.duplicate_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.remove_action)

    def create_layout(self):
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 0)
        toolbar.addWidget(self.size_slider)
        toolbar.addStretch()
        toolbar.addWidget(QtWidgets.QLabel("View:"))
        toolbar.addWidget(self.projection_combo)

        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(2)
        main.addLayout(toolbar)
        main.addWidget(self.list_widget)

    def create_connections(self):
        self.size_slider.valueChanged.connect(self._on_size_changed)
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.itemChanged.connect(self._on_item_renamed)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.projection_combo.currentTextChanged.connect(self._on_projection_changed)
        self.color_action.triggered.connect(self._on_compact_color_pick)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _grid_size(self) -> QtCore.QSize:
        """Fixed cell size: icon width + small padding for the label row."""
        w = self._size + 12
        h = self._size + 28
        return QtCore.QSize(w, h)

    # ------------------------------------------------------------------
    # Public API — full load
    # ------------------------------------------------------------------

    def populate(self, shapes: list) -> None:
        """Load shape dicts from the database and render thumbnails.

        Args:
            shapes: List of shape dicts as returned by ``db.get_all_shapes()``.
        """
        self._shapes = shapes
        _cached_render.cache_clear()
        self.list_widget.clear()
        for shape in shapes:
            pixmap = _cached_render(
                shape.get("cv_data"), shape.get("degree", 1),
                self._size, self._projection, shape.get("color"),
            )
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(pixmap), shape["label"])
            item.setData(QtCore.Qt.UserRole, shape["name"])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            item.setToolTip(shape["label"])
            self.list_widget.addItem(item)

    def selected_key(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def selected_keys(self) -> list:
        """Return all selected shape keys."""
        return [item.data(QtCore.Qt.UserRole)
                for item in self.list_widget.selectedItems()]

    def update_shape_color(self, shape_name: str, rgb: tuple | None) -> None:
        """Update the stored color for a shape and refresh its thumbnail.

        Pass None to reset to the default color.
        """
        for i, shape in enumerate(self._shapes):
            if shape["name"] == shape_name:
                shape["color"] = encode_color(rgb) if rgb else None
                item = self.list_widget.item(i)
                if item is None:
                    continue
                pixmap = _cached_render(
                    shape.get("cv_data"), shape.get("degree", 1),
                    self._size, self._projection, shape.get("color"),
                )
                item.setIcon(QtGui.QIcon(pixmap))
                break

    # ------------------------------------------------------------------
    # Public API — granular updates
    # ------------------------------------------------------------------

    def add_shape_item(self, shape: dict) -> None:
        """Append one shape item without rebuilding the full list."""
        pixmap = _cached_render(
            shape.get("cv_data"), shape.get("degree", 1),
            self._size, self._projection, shape.get("color"),
        )
        item = QtWidgets.QListWidgetItem(QtGui.QIcon(pixmap), shape["label"])
        item.setData(QtCore.Qt.UserRole, shape["name"])
        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
        item.setToolTip(shape["label"])
        self._shapes.append(shape)
        self.list_widget.addItem(item)

    def remove_shape_items(self, keys: list) -> None:
        """Remove shapes by key without rebuilding the full list."""
        key_set = set(keys)
        self._shapes = [s for s in self._shapes if s["name"] not in key_set]
        for i in range(self.list_widget.count() - 1, -1, -1):
            item = self.list_widget.item(i)
            if item and item.data(QtCore.Qt.UserRole) in key_set:
                self.list_widget.takeItem(i)

    def rename_shape_item(self, old_key: str, new_key: str, new_label: str) -> None:
        """Update key and label of one item in-place."""
        for shape in self._shapes:
            if shape["name"] == old_key:
                shape["name"] = new_key
                shape["label"] = new_label
                break
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(QtCore.Qt.UserRole) == old_key:
                self.list_widget.blockSignals(True)
                item.setData(QtCore.Qt.UserRole, new_key)
                item.setText(new_label)
                item.setToolTip(new_label)
                self.list_widget.blockSignals(False)
                break

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item) -> None:
        """Enter edit mode on double-click so the user can rename."""
        self.list_widget.editItem(item)

    def _on_item_renamed(self, item) -> None:
        """Emit rename signal when the user finishes editing a label."""
        old_key = item.data(QtCore.Qt.UserRole)
        new_label = item.text().strip()
        if not new_label:
            # Revert to old label
            row = self.list_widget.row(item)
            if 0 <= row < len(self._shapes):
                item.setText(self._shapes[row]["label"])
            return
        # Check if it actually changed
        row = self.list_widget.row(item)
        if 0 <= row < len(self._shapes) and self._shapes[row]["label"] == new_label:
            return
        self.shape_renamed.emit(old_key, new_label)

    def _on_size_changed(self, value: int) -> None:
        self._size = IMAGE_SIZES[value]
        self.list_widget.setIconSize(QtCore.QSize(self._size, self._size))
        self.list_widget.setGridSize(self._grid_size())
        for i, shape in enumerate(self._shapes):
            item = self.list_widget.item(i)
            if item is None:
                continue
            pixmap = _cached_render(
                shape.get("cv_data"), shape.get("degree", 1),
                self._size, self._projection, shape.get("color"),
            )
            item.setIcon(QtGui.QIcon(pixmap))

    def _on_item_changed(self, current, _previous) -> None:
        if current:
            self.shape_selected.emit(current.data(QtCore.Qt.UserRole))

    def _show_context_menu(self, pos) -> None:
        self._context_item = self.list_widget.itemAt(pos)
        self.context_menu.exec_(self.list_widget.mapToGlobal(pos))

    def _on_projection_changed(self, projection: str) -> None:
        """Re-render all thumbnails with the new projection."""
        self._projection = projection
        for i, shape in enumerate(self._shapes):
            item = self.list_widget.item(i)
            if item is None:
                continue
            pixmap = _cached_render(
                shape.get("cv_data"), shape.get("degree", 1),
                self._size, projection, shape.get("color"),
            )
            item.setIcon(QtGui.QIcon(pixmap))

    def _current_color_pick_shape(self):
        """Return (shape_name, initial_rgb) for the context-menu item."""
        item = getattr(self, "_context_item", None)
        if item is None:
            return None, None
        shape_name = item.data(QtCore.Qt.UserRole)
        initial = (1.0, 1.0, 0.0)
        for shape in self._shapes:
            if shape["name"] == shape_name and shape.get("color"):
                decoded = decode_color(shape["color"])
                if decoded:
                    initial = decoded
                break
        return shape_name, initial

    def _on_compact_color_pick(self) -> None:
        """Open the compact HSV color picker."""
        from app.views.widgets import _CompactColorDialog
        shape_name, initial = self._current_color_pick_shape()
        if shape_name is None:
            return
        dlg = _CompactColorDialog(initial_rgb=initial, parent=self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        rgb = dlg.result_rgb()
        self.update_shape_color(shape_name, rgb)
        self.color_picked.emit(rgb)


# ------------------------------------------------------------------
# Thumbnail renderer (pure Qt, no Maya)
# ------------------------------------------------------------------

def _generate_circle_points(segments: int = 32) -> list:
    """Generate 3D points for a unit circle in the XZ plane (Y=0).

    This matches Maya's ``cmds.circle(normal=(0,1,0))`` so the
    projection system can render it from any view angle.
    """
    pts = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        pts.append([math.cos(angle), 0.0, math.sin(angle)])
    return pts


def _project_points(points: list, size: int, projection: str = "Perspective") -> list:
    """Project 3D CV points onto 2D canvas using the given projection.

    Returns list of (px, py) pixel coords fitted to [padding, size-padding].
    """
    if not points:
        return []

    padding = size * 0.15

    proj_fn = PROJECTIONS.get(projection)
    if proj_fn is None:
        # Isometric projection
        pts2d = _isometric_project(points)
    else:
        pts2d = [proj_fn(p) for p in points]
    xs = [p[0] for p in pts2d]
    ys = [p[1] for p in pts2d]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    x_span = max_x - min_x
    y_span = max_y - min_y
    span = max(x_span, y_span) or 1.0
    draw_area = size - 2 * padding

    # Center the shape when one axis is shorter than the other
    x_offset = (span - x_span) / 2
    y_offset = (span - y_span) / 2

    result = []
    for x, y in pts2d:
        px = padding + ((x - min_x + x_offset) / span) * draw_area
        py = padding + ((max_y + y_offset - y) / span) * draw_area  # flip Y
        result.append((px, py))
    return result


def _render_shape_preview(
    cv_data: list | dict | None, degree: int, size: int,
    projection: str = "Perspective",
    color: tuple | None = None,
) -> QtGui.QPixmap:
    """Draw a 2D thumbnail of a shape using QPainter.

    Args:
        cv_data: Either a flat list of [x,y,z] CV positions (old format),
                 a v2 multi-shape dict, or None (draws a circle fallback).
        degree:  Curve degree for single-shape fallback.
        size:    Pixel size of the output pixmap.
        projection: Name of the 2D projection to use.
    """
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(50, 50, 50))

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    if color:
        r, g, b = [int(c * 255) for c in color]
        pen_color = QtGui.QColor(r, g, b)
    else:
        pen_color = QtGui.QColor(200, 200, 200)
    pen = QtGui.QPen(pen_color)
    pen.setWidth(max(1, size // 48))
    painter.setPen(pen)

    # Detect format and build a list of (cv_list, form) tuples.
    # form: 0 = open, 1 = closed, 2 = periodic (also closed visually).
    if isinstance(cv_data, dict) and cv_data.get("v") == 2:
        shapes_to_draw = [(s["cv"], s.get("form", 0)) for s in cv_data["shapes"]]
    elif isinstance(cv_data, dict) and cv_data.get("v") == 1:
        shapes_to_draw = [(cv_data["cv"], cv_data.get("form", 0))]
    elif cv_data is not None:
        shapes_to_draw = [(cv_data, 0)]
    else:
        # Circle fallback — always visually closed.
        shapes_to_draw = [(_generate_circle_points(), 1)]

    # Project all shapes together so they share the same normalisation.
    all_points = [p for cv_list, _form in shapes_to_draw for p in cv_list]
    shape_info = [(len(cv_list), form) for cv_list, form in shapes_to_draw]
    all_pts_2d = _project_points(all_points, size, projection)

    idx = 0
    for count, form in shape_info:
        pts = all_pts_2d[idx:idx + count]
        idx += count
        if len(pts) >= 2:
            path = QtGui.QPainterPath()
            path.moveTo(*pts[0])
            for pt in pts[1:]:
                path.lineTo(*pt)
            if form:
                path.closeSubpath()
            painter.drawPath(path)

    painter.end()
    return pixmap
