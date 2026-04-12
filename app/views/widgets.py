"""
Shared widget primitives used across all views.
"""
import math
from abc import ABC, abstractmethod

from app.compat import QtCore, QtGui, QtWidgets

_SWATCH_COUNT = 8
_SETTINGS_ORG = "Cesar Daniel Franco"
_SETTINGS_APP = "ControlMe"
_PALETTE_KEY = "color_palette"


# ---------------------------------------------------------------------------
# Gradient slider  (for H / S / V channels)
# ---------------------------------------------------------------------------

class _GradientSlider(QtWidgets.QWidget):
    """Horizontal slider with a painted color-gradient track."""

    value_changed = QtCore.Signal(float)   # 0.0 – 1.0

    _BAR_H   = 14
    _HANDLE_W = 7

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value: float = 0.0
        self._stops: list  = []          # list of (pos_0_1, QColor)
        self.setFixedHeight(24)
        self.setCursor(QtCore.Qt.SizeHorCursor)

    def set_stops(self, stops: list) -> None:
        self._stops = stops
        self.update()

    def set_value(self, v: float) -> None:
        self._value = max(0.0, min(1.0, v))
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(200, 24)

    # ── paint ────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        w, h  = self.width(), self.height()
        hw    = self._HANDLE_W // 2
        bar_x = hw + 1
        bar_w = w - (hw + 1) * 2
        bar_y = (h - self._BAR_H) // 2
        bar   = QtCore.QRectF(bar_x, bar_y, bar_w, self._BAR_H)

        if self._stops:
            grad = QtGui.QLinearGradient(bar.left(), 0, bar.right(), 0)
            for pos, color in self._stops:
                grad.setColorAt(pos, color)
            p.fillRect(bar, grad)

        p.setPen(QtGui.QColor(60, 60, 60))
        p.drawRect(bar)

        # vertical-bar handle
        hx     = bar.left() + self._value * bar.width()
        handle = QtCore.QRectF(hx - hw, bar_y - 3, self._HANDLE_W, self._BAR_H + 6)
        p.setPen(QtGui.QColor(40, 40, 40))
        p.setBrush(QtGui.QColor(230, 230, 230))
        p.drawRect(handle)

    # ── interaction ──────────────────────────────────────────────────────

    def _value_from_x(self, x: int) -> float:
        hw    = self._HANDLE_W // 2
        bar_w = self.width() - (hw + 1) * 2
        if bar_w <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - hw - 1) / bar_w))

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.set_value(self._value_from_x(event.x()))
            self.value_changed.emit(self._value)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & QtCore.Qt.LeftButton:
            self.set_value(self._value_from_x(event.x()))
            self.value_changed.emit(self._value)


# ---------------------------------------------------------------------------
# Hue-ring + SV-square color wheel
# ---------------------------------------------------------------------------

class _ColorWheel(QtWidgets.QWidget):
    """Interactive color wheel: outer hue ring + inner saturation/value square."""

    color_changed = QtCore.Signal(float, float, float)   # h, s, v  (0–1)

    _RING_FRAC = 0.15     # ring thickness as fraction of outer radius

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._h: float = 0.0
        self._s: float = 1.0
        self._v: float = 1.0
        self._dragging      = None   # 'ring' | 'square' | None
        self._ring_px       = None   # cached QPixmap for the ring
        self._ring_px_size  = 0
        self._sq_px         = None   # cached QPixmap for the SV square
        self._sq_px_hue     = -1.0

    def set_hsv(self, h: float, s: float, v: float) -> None:
        if h != self._h:
            self._sq_px = None          # invalidate SV cache on hue change
        self._h, self._s, self._v = h, s, v
        self.update()

    # ── geometry helpers ──────────────────────────────────────────────────

    def _cx_cy(self):
        return self.width() / 2.0, self.height() / 2.0

    def _outer_r(self) -> float:
        return min(self.width(), self.height()) / 2.0 - 2.0

    def _inner_r(self) -> float:
        return self._outer_r() * (1.0 - self._RING_FRAC * 2)

    def _sq_rect(self) -> QtCore.QRectF:
        cx, cy = self._cx_cy()
        half   = self._inner_r() / math.sqrt(2) * 0.93
        return QtCore.QRectF(cx - half, cy - half, half * 2, half * 2)

    # ── pixmap builders ───────────────────────────────────────────────────

    def _build_ring(self, size: int) -> QtGui.QPixmap:
        """Hue ring using a conical gradient.

        Stop t (0–1) maps to hue t, placed at angle t*360° CCW from east
        (Qt/math convention).  The indicator position uses the same mapping.
        """
        img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        cx    = cy    = size / 2.0
        r_out = size / 2.0 - 2.0
        r_in  = r_out * (1.0 - self._RING_FRAC * 2)

        grad = QtGui.QConicalGradient(cx, cy, 0.0)
        for i in range(361):
            t = i / 360.0
            grad.setColorAt(t, QtGui.QColor.fromHsvF(t, 1.0, 1.0))

        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QPointF(cx, cy), r_out, r_out)

        p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
        p.drawEllipse(QtCore.QPointF(cx, cy), r_in, r_in)
        p.end()
        return QtGui.QPixmap.fromImage(img)

    def _build_sq(self, sq_size: int) -> QtGui.QPixmap:
        img = QtGui.QImage(sq_size, sq_size, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.white)
        p = QtGui.QPainter(img)

        # horizontal: white → pure hue  (saturation axis)
        pure = QtGui.QColor.fromHsvF(self._h, 1.0, 1.0)
        gh   = QtGui.QLinearGradient(0, 0, sq_size, 0)
        gh.setColorAt(0.0, QtGui.QColor(255, 255, 255))
        gh.setColorAt(1.0, pure)
        p.fillRect(0, 0, sq_size, sq_size, gh)

        # vertical overlay: transparent → black  (value axis)
        gv = QtGui.QLinearGradient(0, 0, 0, sq_size)
        gv.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        gv.setColorAt(1.0, QtGui.QColor(0, 0, 0, 255))
        p.fillRect(0, 0, sq_size, sq_size, gv)

        p.end()
        return QtGui.QPixmap.fromImage(img)

    # ── paint ────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p  = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        cx, cy = self._cx_cy()
        r_out  = self._outer_r()
        size   = int(r_out * 2 + 4)

        # hue ring
        if self._ring_px is None or self._ring_px_size != size:
            self._ring_px      = self._build_ring(size)
            self._ring_px_size = size
        p.drawPixmap(int(cx - size / 2), int(cy - size / 2), self._ring_px)

        # hue indicator circle on the ring
        r_mid  = r_out * (1.0 - self._RING_FRAC)
        angle  = self._h * 2.0 * math.pi
        ix     = cx + r_mid * math.cos(angle)
        iy     = cy - r_mid * math.sin(angle)    # y-flip for screen coords
        rw     = r_out * self._RING_FRAC * 0.85
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QPointF(ix, iy), rw, rw)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
        p.drawEllipse(QtCore.QPointF(ix, iy), rw + 1.5, rw + 1.5)

        # SV square
        sq      = self._sq_rect()
        sq_size = int(sq.width())
        if self._sq_px is None or abs(self._sq_px_hue - self._h) > 1e-4:
            self._sq_px     = self._build_sq(sq_size)
            self._sq_px_hue = self._h
        p.drawPixmap(sq.toRect(), self._sq_px)

        # SV indicator circle
        sx = sq.left() + self._s * sq.width()
        sy = sq.top()  + (1.0 - self._v) * sq.height()
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QPointF(sx, sy), 5.0, 5.0)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
        p.drawEllipse(QtCore.QPointF(sx, sy), 6.5, 6.5)

    # ── hit-test ──────────────────────────────────────────────────────────

    def _hit_test(self, pos: QtCore.QPoint):
        cx, cy = self._cx_cy()
        dx, dy = pos.x() - cx, pos.y() - cy
        dist   = math.sqrt(dx * dx + dy * dy)
        if self._inner_r() < dist <= self._outer_r() + 3:
            return 'ring'
        if self._sq_rect().contains(QtCore.QPointF(pos)):
            return 'square'
        return None

    def _update_from_pos(self, pos: QtCore.QPoint) -> None:
        cx, cy = self._cx_cy()
        if self._dragging == 'ring':
            dx, dy   = pos.x() - cx, pos.y() - cy
            # atan2 with -dy to convert screen y-down → math y-up
            angle    = math.atan2(-dy, dx)
            self._h  = (angle / (2.0 * math.pi)) % 1.0
            self._sq_px = None
        elif self._dragging == 'square':
            sq       = self._sq_rect()
            self._s  = max(0.0, min(1.0, (pos.x() - sq.left()) / sq.width()))
            self._v  = max(0.0, min(1.0, 1.0 - (pos.y() - sq.top()) / sq.height()))
        self.update()
        self.color_changed.emit(self._h, self._s, self._v)

    # ── mouse ────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._dragging = self._hit_test(event.pos())
            if self._dragging:
                self._update_from_pos(event.pos())

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() & QtCore.Qt.LeftButton) and self._dragging:
            self._update_from_pos(event.pos())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None


# ---------------------------------------------------------------------------
# Color picker dialog  (Maya-style layout)
# ---------------------------------------------------------------------------

class _CompactColorDialog(QtWidgets.QDialog):
    """HSV color picker styled after Maya's color editor.

    Layout::

        ┌─ Color History ──────────────────────────────────────────┐
        │  [large preview]  [2×4 saved swatches]                   │
        └──────────────────────────────────────────────────────────┘
        ┌─ Mixing Color ───────────────────────┐  ┌─ Color Wheel ─┐
        │  H: [gradient slider]  [spinbox]     │  │               │
        │  S: [gradient slider]  [spinbox]     │  │  ring + SV    │
        │  V: [gradient slider]  [spinbox]     │  │               │
        │  Mixing Color Space: [combo]         │  └───────────────┘
        └──────────────────────────────────────┘
        [ OK ]  [ Cancel ]

    Swatch interaction:
        Left-click  → load saved color into sliders.
        Right-click → save current color into that slot.
    """

    def __init__(self, initial_rgb: tuple = (1.0, 1.0, 1.0), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color")
        self.setFixedSize(490, 295)
        self.setWindowModality(QtCore.Qt.WindowModal)

        qc     = QtGui.QColor.fromRgbF(*initial_rgb)
        self._h: float = max(0.0, qc.hsvHueF())   # hsvHueF() == -1 for greys
        self._s: float = qc.hsvSaturationF()
        self._v: float = qc.valueF()

        # ── Color History ─────────────────────────────────────────────────
        self._preview = QtWidgets.QLabel()
        self._preview.setObjectName("colorPreview")
        self._preview.setFixedSize(52, 52)
        self._preview.setFrameShape(QtWidgets.QFrame.Box)

        self._saved_colors: list = self._load_palette()
        self._swatch_btns:  list = []
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        for i in range(_SWATCH_COUNT):
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(21, 21)
            btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            btn.clicked.connect(lambda *a, idx=i: self._load_swatch(idx))
            btn.customContextMenuRequested.connect(lambda *a, idx=i: self._save_swatch(idx))
            self._swatch_btns.append(btn)
            grid.addWidget(btn, i // 4, i % 4)   # 2 rows × 4 cols

        history_inner = QtWidgets.QHBoxLayout()
        history_inner.setSpacing(8)
        history_inner.addWidget(self._preview)
        history_inner.addLayout(grid)
        history_inner.addStretch()
        history_box = QtWidgets.QGroupBox("Color History")
        history_box.setLayout(history_inner)

        # ── HSV gradient sliders ──────────────────────────────────────────
        self._h_sl = _GradientSlider()
        self._s_sl = _GradientSlider()
        self._v_sl = _GradientSlider()

        self._h_sp = QtWidgets.QDoubleSpinBox()
        self._s_sp = QtWidgets.QDoubleSpinBox()
        self._v_sp = QtWidgets.QDoubleSpinBox()

        self._h_sp.setRange(0, 360); self._h_sp.setDecimals(2); self._h_sp.setFixedWidth(72)
        self._s_sp.setRange(0, 1);   self._s_sp.setDecimals(3); self._s_sp.setFixedWidth(72)
        self._v_sp.setRange(0, 1);   self._v_sp.setDecimals(3); self._v_sp.setFixedWidth(72)

        form = QtWidgets.QGridLayout()
        form.setVerticalSpacing(6)
        for row, (lbl, sl, sp) in enumerate([
            ("H:", self._h_sl, self._h_sp),
            ("S:", self._s_sl, self._s_sp),
            ("V:", self._v_sl, self._v_sp),
        ]):
            form.addWidget(QtWidgets.QLabel(lbl), row, 0)
            form.addWidget(sl, row, 1)
            form.addWidget(sp, row, 2)

        cs_combo = QtWidgets.QComboBox()
        cs_combo.addItem("Rendering Space")
        cs_row = QtWidgets.QHBoxLayout()
        cs_row.addWidget(QtWidgets.QLabel("Mixing Color Space:"))
        cs_row.addWidget(cs_combo)
        cs_row.addStretch()

        mixing_inner = QtWidgets.QVBoxLayout()
        mixing_inner.setSpacing(4)
        mixing_inner.addLayout(form)
        mixing_inner.addLayout(cs_row)
        mixing_box = QtWidgets.QGroupBox("Mixing Color in Preferred Color Space")
        mixing_box.setLayout(mixing_inner)

        # ── Color wheel ───────────────────────────────────────────────────
        self._wheel = _ColorWheel()
        self._wheel.setFixedSize(155, 155)

        hsv_lbl = QtWidgets.QLabel("HSV")
        hsv_lbl.setAlignment(QtCore.Qt.AlignRight)
        right_col = QtWidgets.QVBoxLayout()
        right_col.addWidget(self._wheel)
        right_col.addWidget(hsv_lbl)
        right_col.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────
        self._buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )

        # ── Main layout ───────────────────────────────────────────────────
        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(history_box)
        left_col.addWidget(mixing_box)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(8)
        content.addLayout(left_col)
        content.addLayout(right_col)

        main = QtWidgets.QVBoxLayout(self)
        main.setSpacing(6)
        main.addLayout(content)
        main.addWidget(self._buttons)

        # ── Connections ───────────────────────────────────────────────────
        self._h_sl.value_changed.connect(self._on_h_slider)
        self._s_sl.value_changed.connect(self._on_s_slider)
        self._v_sl.value_changed.connect(self._on_v_slider)
        self._h_sp.valueChanged.connect(self._on_h_sp)
        self._s_sp.valueChanged.connect(self._on_s_sp)
        self._v_sp.valueChanged.connect(self._on_v_sp)
        self._wheel.color_changed.connect(self._on_wheel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._refresh_swatches()
        self._sync_all()

    # ── full sync ─────────────────────────────────────────────────────────

    def _sync_all(self) -> None:
        """Push self._h/_s/_v to all widgets atomically (no feedback loops)."""
        for w in (self._h_sl, self._s_sl, self._v_sl,
                  self._h_sp, self._s_sp, self._v_sp):
            w.blockSignals(True)

        self._h_sl.set_value(self._h)
        self._s_sl.set_value(self._s)
        self._v_sl.set_value(self._v)
        self._h_sp.setValue(self._h * 360.0)
        self._s_sp.setValue(self._s)
        self._v_sp.setValue(self._v)

        for w in (self._h_sl, self._s_sl, self._v_sl,
                  self._h_sp, self._s_sp, self._v_sp):
            w.blockSignals(False)

        self._update_slider_stops()
        self._wheel.set_hsv(self._h, self._s, self._v)
        self._update_preview()

    def _update_slider_stops(self) -> None:
        """Recolor gradient tracks to reflect current HSV context."""
        # H: rainbow at current S and V
        self._h_sl.set_stops([
            (i / 12.0, QtGui.QColor.fromHsvF(i / 12.0, self._s, self._v))
            for i in range(13)
        ])
        # S: grey → pure hue  (at current V)
        self._s_sl.set_stops([
            (0.0, QtGui.QColor.fromHsvF(self._h, 0.0, self._v)),
            (1.0, QtGui.QColor.fromHsvF(self._h, 1.0, self._v)),
        ])
        # V: black → full color
        self._v_sl.set_stops([
            (0.0, QtGui.QColor(0, 0, 0)),
            (1.0, QtGui.QColor.fromHsvF(self._h, self._s, 1.0)),
        ])

    def _update_preview(self) -> None:
        c = QtGui.QColor.fromHsvF(self._h, self._s, self._v)
        # Use #objectName selector so the color is strictly scoped to this
        # label and cannot cascade to parent GroupBox / Dialog.
        self._preview.setStyleSheet(
            f"QLabel#colorPreview {{ background-color: rgb({c.red()},{c.green()},{c.blue()}); border: 1px solid #555; }}"
        )

    # ── slider slots ─────────────────────────────────────────────────────

    def _on_h_slider(self, v: float) -> None:
        self._h = v
        self._h_sp.blockSignals(True); self._h_sp.setValue(v * 360.0); self._h_sp.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    def _on_s_slider(self, v: float) -> None:
        self._s = v
        self._s_sp.blockSignals(True); self._s_sp.setValue(v); self._s_sp.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    def _on_v_slider(self, v: float) -> None:
        self._v = v
        self._v_sp.blockSignals(True); self._v_sp.setValue(v); self._v_sp.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    # ── spinbox slots ─────────────────────────────────────────────────────

    def _on_h_sp(self, val: float) -> None:
        self._h = val / 360.0
        self._h_sl.blockSignals(True); self._h_sl.set_value(self._h); self._h_sl.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    def _on_s_sp(self, val: float) -> None:
        self._s = val
        self._s_sl.blockSignals(True); self._s_sl.set_value(self._s); self._s_sl.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    def _on_v_sp(self, val: float) -> None:
        self._v = val
        self._v_sl.blockSignals(True); self._v_sl.set_value(self._v); self._v_sl.blockSignals(False)
        self._update_slider_stops(); self._wheel.set_hsv(self._h, self._s, self._v); self._update_preview()

    # ── wheel slot ────────────────────────────────────────────────────────

    def _on_wheel(self, h: float, s: float, v: float) -> None:
        self._h, self._s, self._v = h, s, v
        for w in (self._h_sl, self._s_sl, self._v_sl,
                  self._h_sp, self._s_sp, self._v_sp):
            w.blockSignals(True)
        self._h_sl.set_value(h); self._s_sl.set_value(s); self._v_sl.set_value(v)
        self._h_sp.setValue(h * 360.0); self._s_sp.setValue(s); self._v_sp.setValue(v)
        for w in (self._h_sl, self._s_sl, self._v_sl,
                  self._h_sp, self._s_sp, self._v_sp):
            w.blockSignals(False)
        self._update_slider_stops()
        self._update_preview()

    def result_rgb(self) -> tuple:
        """Return the selected color as ``(r, g, b)`` floats 0–1."""
        c = QtGui.QColor.fromHsvF(self._h, self._s, self._v)
        return (c.redF(), c.greenF(), c.blueF())

    # ── palette persistence ───────────────────────────────────────────────

    @staticmethod
    def _load_palette() -> list:
        settings = QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        raw      = settings.value(_PALETTE_KEY) or []
        colors: list = []
        for item in raw:
            try:
                parts = [float(x) for x in str(item).split(",")]
                colors.append(tuple(parts) if len(parts) == 3 else None)
            except (ValueError, TypeError):
                colors.append(None)
        while len(colors) < _SWATCH_COUNT:
            colors.append(None)
        return colors[:_SWATCH_COUNT]

    @staticmethod
    def _save_palette(colors: list) -> None:
        settings = QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue(_PALETTE_KEY, [
            f"{c[0]},{c[1]},{c[2]}" if c is not None else ""
            for c in colors
        ])

    def _refresh_swatches(self) -> None:
        tip = "Left-click: load  |  Right-click: save current color"
        for i, btn in enumerate(self._swatch_btns):
            c = self._saved_colors[i]
            if c is not None:
                r, g, b = (int(x * 255) for x in c)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: rgb({r},{g},{b}); border: 1px solid #555; }}")
            else:
                btn.setStyleSheet("QPushButton { background-color: #333; border: 1px solid #555; }")
            btn.setToolTip(tip)

    def _load_swatch(self, idx: int) -> None:
        c = self._saved_colors[idx]
        if c is None:
            return
        qc       = QtGui.QColor.fromRgbF(*c)
        self._h  = max(0.0, qc.hsvHueF())
        self._s  = qc.hsvSaturationF()
        self._v  = qc.valueF()
        self._sync_all()

    def _save_swatch(self, idx: int) -> None:
        c = QtGui.QColor.fromHsvF(self._h, self._s, self._v)
        self._saved_colors[idx] = (c.redF(), c.greenF(), c.blueF())
        self._save_palette(self._saved_colors)
        self._refresh_swatches()


# ---------------------------------------------------------------------------
# Public color picker entry point
# ---------------------------------------------------------------------------

def open_color_picker(
    initial_rgb: tuple = (1.0, 1.0, 1.0),
    parent=None,
    compact: bool = False,
) -> tuple | None:
    """Open a color picker suited to the current environment.

    Args:
        initial_rgb: Starting color as ``(r, g, b)`` floats 0-1.
        parent:      Parent widget.
        compact:     When ``True`` always uses the compact HSV popup
                     regardless of environment.

    Returns:
        ``(r, g, b)`` floats 0-1, or ``None`` if cancelled.
    """
    from app.compat import is_maya

    if compact:
        dlg = _CompactColorDialog(initial_rgb=initial_rgb, parent=parent)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            return dlg.result_rgb()
        return None

    if is_maya():
        import maya.cmds as cmds
        r, g, b = initial_rgb
        cmds.colorEditor(rgbValue=(r, g, b))
        if cmds.colorEditor(query=True, result=True):
            result = cmds.colorEditor(query=True, rgb=True)
            return (float(result[0]), float(result[1]), float(result[2]))
        return None

    r8, g8, b8 = [int(c * 255) for c in initial_rgb]
    color = QtWidgets.QColorDialog.getColor(
        QtGui.QColor(r8, g8, b8), parent, "Color"
    )
    if color.isValid():
        return (color.redF(), color.greenF(), color.blueF())
    return None


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class AbstractWidget(ABC):
    """Base class that enforces the create_widgets / create_layout /
    create_connections pattern across all custom widgets."""

    def __init__(self):
        super().__init__()
        self.create_widgets()
        self.create_layout()
        self.create_connections()

    @abstractmethod
    def create_widgets(self):
        pass

    @abstractmethod
    def create_layout(self):
        pass

    @abstractmethod
    def create_connections(self):
        pass


class IconPushButton(QtWidgets.QPushButton):
    """Flat push button with an icon and no visible border."""

    def __init__(self, icon: str, size: int = 24) -> None:
        super().__init__()
        self.setFlat(True)
        self.setIcon(QtGui.QIcon(icon))
        self.setFixedSize(size, size)
        self.setIconSize(QtCore.QSize(size, size))


class ColorSwatch(QtWidgets.QPushButton):
    """Small button that shows a solid color and opens the compact HSV picker."""

    color_changed = QtCore.Signal(tuple)   # emits (r, g, b) in 0-1 range

    def __init__(self, initial_color: tuple = (1.0, 1.0, 1.0)) -> None:
        super().__init__()
        self.setObjectName("colorSwatch")
        self.setFixedSize(24, 24)
        self._color = initial_color
        self._update_style()
        self.clicked.connect(self._open_compact)

    def _update_style(self) -> None:
        r, g, b = [int(c * 255) for c in self._color]
        self.setStyleSheet(
            f"QPushButton#colorSwatch {{ background-color: rgb({r},{g},{b}); border: 1px solid #555; }}"
        )

    def _open_compact(self) -> None:
        dlg = _CompactColorDialog(initial_rgb=self._color, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._color = dlg.result_rgb()
            self._update_style()
            self.color_changed.emit(self._color)

    def set_color(self, rgb: tuple) -> None:
        """Update the displayed color without emitting color_changed."""
        self._color = rgb
        self._update_style()

    @property
    def color(self) -> tuple:
        return self._color
