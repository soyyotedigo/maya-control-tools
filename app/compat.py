"""
Compatibility layer — PySide2/6 imports and Maya detection.

All views should import Qt bindings from this module instead of
importing PySide2 or PySide6 directly.
"""

from __future__ import annotations

import inspect
import os
import sys

# ------------------------------------------------------------------
# PySide abstraction
# ------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _build_qt_test_stub():
    """Return a tiny Qt-like API for headless test environments.

    This is only used when neither PySide2 nor PySide6 can be imported,
    such as CI runners missing system GUI libraries.
    """

    class _BoundSignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            for callback in list(self._callbacks):
                try:
                    callback(*args, **kwargs)
                except TypeError:
                    signature = inspect.signature(callback)
                    params = list(signature.parameters.values())
                    if any(
                        param.kind == inspect.Parameter.VAR_POSITIONAL
                        for param in params
                    ):
                        raise
                    positional = [
                        param
                        for param in params
                        if param.kind
                        in (
                            inspect.Parameter.POSITIONAL_ONLY,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        )
                    ]
                    callback(*args[: len(positional)], **kwargs)

        __call__ = emit

    class _SignalDescriptor:
        def __init__(self, *_args, **_kwargs):
            self._name = None

        def __set_name__(self, _owner, name):
            self._name = "__signal_%s" % name

        def __get__(self, instance, _owner):
            if instance is None:
                return self
            signal = instance.__dict__.get(self._name)
            if signal is None:
                signal = _BoundSignal()
                instance.__dict__[self._name] = signal
            return signal

    def _slot(*_args, **_kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    class _QtEnum:
        UserRole = 32
        CustomContextMenu = 1
        LeftButton = 1
        NoButton = 0
        NoModifier = 0
        Horizontal = 1
        ScrollBarAlwaysOff = 1
        CopyAction = 1
        ItemIsEditable = 1 << 9
        transparent = 0
        white = 1
        SizeHorCursor = 2
        NoPen = 3
        NoBrush = 4
        Window = 5
        AlignCenter = 0x84
        AlignLeft = 0x01
        AlignRight = 0x02
        AlignHCenter = 0x04
        AlignVCenter = 0x80
        Vertical = 2

    class _QEvent:
        MouseButtonRelease = 2
        DragEnter = 3
        DragMove = 4
        Drop = 5

    class _QPoint:
        def __init__(self, x=0, y=0):
            self._x = x
            self._y = y

        def x(self):
            return self._x

        def y(self):
            return self._y

        def __sub__(self, other):
            return _QPoint(self._x - other._x, self._y - other._y)

        def manhattanLength(self):
            return abs(self._x) + abs(self._y)

    class _QPointF(_QPoint):
        pass

    class _QSize:
        def __init__(self, width=0, height=0):
            self._width = width
            self._height = height

        def width(self):
            return self._width

        def height(self):
            return self._height

        def __eq__(self, other):
            return (
                isinstance(other, _QSize)
                and self._width == other._width
                and self._height == other._height
            )

        def __repr__(self):
            return "QSize(%s, %s)" % (self._width, self._height)

    class _QRectF:
        def __init__(self, x=0, y=0, width=0, height=0):
            self._x = x
            self._y = y
            self._width = width
            self._height = height

        def left(self):
            return self._x

        def right(self):
            return self._x + self._width

        def width(self):
            return self._width

    class _QMimeData:
        def __init__(self):
            self._data = {}

        def setData(self, key, value):
            self._data[key] = value

    class _QtCore:
        Signal = _SignalDescriptor
        Slot = staticmethod(_slot)
        Qt = _QtEnum
        QSize = _QSize
        QPoint = _QPoint
        QPointF = _QPointF
        QRectF = _QRectF
        QEvent = _QEvent
        QMimeData = _QMimeData

    class _QObject:
        def __init__(self, parent=None):
            self.parent = parent

        def installEventFilter(self, _obj):
            return None

    class _QSettings:
        def __init__(self, *_args, **_kwargs):
            self._values = {}

        def value(self, key):
            return self._values.get(key)

        def setValue(self, key, value):
            self._values[key] = value

    class _QItemSelectionModel:
        NoUpdate = 0

    _QtCore.QObject = _QObject
    _QtCore.QSettings = _QSettings
    _QtCore.QItemSelectionModel = _QItemSelectionModel

    class _QColor:
        def __init__(self, *args):
            self.args = args

        @staticmethod
        def fromHsvF(h, s, v):
            return _QColor(h, s, v)

    class _QPixmap:
        def __init__(self, width=0, height=0):
            self._width = width
            self._height = height
            self._fill = None

        def fill(self, color):
            self._fill = color

        def width(self):
            return self._width

        def height(self):
            return self._height

        @staticmethod
        def fromImage(image):
            return _QPixmap(image.width(), image.height())

    class _QImage:
        Format_ARGB32 = 0

        def __init__(self, width=0, height=0, _format=None):
            self._width = width
            self._height = height

        def fill(self, _color):
            return None

        def width(self):
            return self._width

        def height(self):
            return self._height

    class _QPainter:
        Antialiasing = 1
        CompositionMode_Clear = 2

        def __init__(self, _target=None):
            self._target = _target

        def setRenderHint(self, *_args, **_kwargs):
            return None

        def fillRect(self, *_args, **_kwargs):
            return None

        def setPen(self, *_args, **_kwargs):
            return None

        def drawRect(self, *_args, **_kwargs):
            return None

        def setBrush(self, *_args, **_kwargs):
            return None

        def drawEllipse(self, *_args, **_kwargs):
            return None

        def setCompositionMode(self, *_args, **_kwargs):
            return None

        def drawPixmap(self, *_args, **_kwargs):
            return None

        def drawPath(self, *_args, **_kwargs):
            return None

        def end(self):
            return None

    class _QLinearGradient:
        def __init__(self, *_args):
            self.stops = []

        def setColorAt(self, pos, color):
            self.stops.append((pos, color))

    class _QConicalGradient(_QLinearGradient):
        pass

    class _QBrush:
        def __init__(self, color=None):
            self.color = color

    class _QPen:
        def __init__(self, color=None, width=1):
            self.color = color
            self.width = width

        def setWidth(self, width):
            self.width = width

    class _QPainterPath:
        def __init__(self):
            self.points = []

        def moveTo(self, *pt):
            self.points.append(("move", pt))

        def lineTo(self, *pt):
            self.points.append(("line", pt))

        def closeSubpath(self):
            self.points.append(("close",))

    class _QIcon:
        def __init__(self, pixmap=None):
            self._pixmap = pixmap or _QPixmap()

        def pixmap(self, width, height):
            if self._pixmap.width() == width and self._pixmap.height() == height:
                return self._pixmap
            return _QPixmap(width, height)

    class _QDrag:
        def __init__(self, _parent=None):
            self.mime = None
            self.pixmap = None
            self.hotspot = None

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, pixmap):
            self.pixmap = pixmap

        def setHotSpot(self, hotspot):
            self.hotspot = hotspot

        def exec_(self, _action):
            return None

    class _QMouseEvent:
        def __init__(self, _etype, pos, button, buttons, _modifiers):
            self._pos = pos
            self._button = button
            self._buttons = buttons

        def pos(self):
            return self._pos

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

    class _QtGui:
        QColor = _QColor
        QPixmap = _QPixmap
        QImage = _QImage
        QPainter = _QPainter
        QLinearGradient = _QLinearGradient
        QConicalGradient = _QConicalGradient
        QBrush = _QBrush
        QPen = _QPen
        QPainterPath = _QPainterPath
        QIcon = _QIcon
        QDrag = _QDrag
        QMouseEvent = _QMouseEvent

    class _StubFont:
        def setBold(self, _value):
            return None

        def setPointSize(self, _value):
            return None

        def setItalic(self, _value):
            return None

    class _Widget:
        def __init__(self, parent=None):
            self.parent = parent
            self._closed = False
            self._layout = None
            self._tooltip = ""
            self._style = ""
            self._object_name = ""
            self._accept_drops = False
            self._font = _StubFont()

        def font(self):
            return self._font

        def setFont(self, font):
            self._font = font

        def setWordWrap(self, _wrap):
            return None

        def setEnabled(self, enabled):
            self._enabled = bool(enabled)

        def isEnabled(self):
            return getattr(self, "_enabled", True)

        def setMinimumWidth(self, _value):
            return None

        def close(self):
            self._closed = True

        def closeEvent(self, _event):
            return None

        def setFixedHeight(self, _value):
            return None

        def setFixedWidth(self, _value):
            return None

        def setFixedSize(self, *_args):
            return None

        def setCursor(self, _value):
            return None

        def update(self):
            return None

        def setWindowTitle(self, _title):
            return None

        def setWindowIcon(self, _icon):
            return None

        def setWindowFlags(self, _flags):
            return None

        def setMinimumSize(self, *_args):
            return None

        def setStyleSheet(self, style):
            self._style = style

        def setToolTip(self, text):
            self._tooltip = text

        def toolTip(self):
            return self._tooltip

        def setObjectName(self, name):
            self._object_name = name

        def saveGeometry(self):
            return b""

        def restoreGeometry(self, _geo):
            return True

        def show(self):
            return None

        def setParent(self, parent):
            self.parent = parent

        def deleteLater(self):
            return None

        def findChildren(self, _cls):
            return []

        def setAcceptDrops(self, enabled):
            self._accept_drops = bool(enabled)

        def acceptDrops(self):
            return self._accept_drops

        def installEventFilter(self, _obj):
            return None

        def setSizePolicy(self, *_args):
            return None

        def layout(self):
            return self._layout

        def setContextMenuPolicy(self, _policy):
            return None

    class _QApplication:
        _instance = None

        def __init__(self, _args=None):
            _QApplication._instance = self

        @classmethod
        def instance(cls):
            return cls._instance

        @staticmethod
        def startDragDistance():
            return 10

    class _QAction(_Widget):
        triggered = _SignalDescriptor()

        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self.text = text

    class _QMenu(_Widget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._actions = []

        def addAction(self, action):
            if isinstance(action, str):
                action = _QAction(action, self)
            self._actions.append(action)
            return action

        def addSeparator(self):
            self._actions.append(None)

        def exec_(self, _pos):
            return None

    class _QListWidgetItem:
        def __init__(self, *args):
            self._icon = _QIcon()
            self._text = ""
            if len(args) == 1:
                self._text = args[0]
            elif len(args) >= 2:
                self._icon = args[0]
                self._text = args[1]
            self._data = {}
            self._flags = 0
            self._selected = False
            self._tooltip = self._text

        def data(self, role):
            return self._data.get(role)

        def setData(self, role, value):
            self._data[role] = value

        def text(self):
            return self._text

        def setText(self, text):
            self._text = text

        def flags(self):
            return self._flags

        def setFlags(self, flags):
            self._flags = flags

        def setSelected(self, selected):
            self._selected = selected

        def isSelected(self):
            return self._selected

        def setToolTip(self, text):
            self._tooltip = text

        def toolTip(self):
            return self._tooltip

        def icon(self):
            return self._icon

        def setIcon(self, icon):
            self._icon = icon

    class _QListWidget(_Widget):
        currentTextChanged = _SignalDescriptor()
        itemDoubleClicked = _SignalDescriptor()
        itemChanged = _SignalDescriptor()
        customContextMenuRequested = _SignalDescriptor()
        currentItemChanged = _SignalDescriptor()
        itemSelectionChanged = _SignalDescriptor()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._items = []
            self._current_row = -1
            self._blocked = False
            self._icon_size = _QSize()
            self._grid_size = _QSize()

        def addItem(self, item):
            self._items.append(item)

        def clear(self):
            self._items = []
            self._current_row = -1

        def clearSelection(self):
            for item in self._items:
                item.setSelected(False)
            if not self._blocked:
                self.itemSelectionChanged.emit()

        def count(self):
            return len(self._items)

        def item(self, index):
            if 0 <= index < len(self._items):
                return self._items[index]
            return None

        def selectedItems(self):
            return [item for item in self._items if item.isSelected()]

        def setCurrentRow(self, index):
            previous = self.currentItem()
            self._current_row = index
            current = self.currentItem()
            if self._blocked:
                return
            text = current.text() if current else ""
            self.currentTextChanged.emit(text)
            self.currentItemChanged.emit(current, previous)
            self.itemSelectionChanged.emit()

        def setCurrentItem(self, item, _mode=None):
            self.setCurrentRow(self.row(item))

        def currentItem(self):
            return self.item(self._current_row)

        def setSelectionMode(self, _mode):
            return None

        def setEditTriggers(self, _triggers):
            return None

        def setContextMenuPolicy(self, _policy):
            return None

        def blockSignals(self, value):
            self._blocked = value

        def takeItem(self, index):
            if 0 <= index < len(self._items):
                return self._items.pop(index)
            return None

        def row(self, item):
            try:
                return self._items.index(item)
            except ValueError:
                return -1

        def editItem(self, _item):
            return None

        def itemAt(self, pos):
            if isinstance(pos, _QPoint):
                return self.item(pos.y())
            return self.item(0)

        def mapToGlobal(self, pos):
            return pos

        def setViewMode(self, _mode):
            return None

        def setIconSize(self, size):
            self._icon_size = size

        def iconSize(self):
            return self._icon_size

        def setGridSize(self, size):
            self._grid_size = size

        def gridSize(self):
            return self._grid_size

        def setResizeMode(self, _mode):
            return None

        def setMovement(self, _mode):
            return None

        def setSpacing(self, _spacing):
            return None

        def setWordWrap(self, _enabled):
            return None

        def setHorizontalScrollBarPolicy(self, _policy):
            return None

        def mousePressEvent(self, _event):
            return None

        def mouseMoveEvent(self, _event):
            return None

        def mouseReleaseEvent(self, _event):
            return None

    class _QLineEdit(_Widget):
        textChanged = _SignalDescriptor()
        returnPressed = _SignalDescriptor()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._text = ""

        def setPlaceholderText(self, _text):
            return None

        def setClearButtonEnabled(self, _enabled):
            return None

        def setText(self, text):
            self._text = text
            self.textChanged.emit(text)

        def text(self):
            return self._text

        def clear(self):
            self.setText("")

    class _BaseLayout:
        def __init__(self, parent=None):
            self.children = []
            if parent is not None and hasattr(parent, "_layout"):
                parent._layout = self

        def addWidget(self, widget, *_args, **_kwargs):
            self.children.append(widget)

        def addLayout(self, layout, *_args, **_kwargs):
            self.children.append(layout)

        def addStretch(self, *_args):
            self.children.append("stretch")

        def addSpacing(self, value):
            self.children.append(("spacing", value))

        def setSpacing(self, _value):
            return None

        def setContentsMargins(self, *_args):
            return None

        def setMenuBar(self, widget):
            self.children.append(("menubar", widget))

    class _QHBoxLayout(_BaseLayout):
        pass

    class _QVBoxLayout(_BaseLayout):
        pass

    class _QGridLayout(_BaseLayout):
        def setHorizontalSpacing(self, _value):
            return None

        def setVerticalSpacing(self, _value):
            return None

        def setColumnStretch(self, *_args):
            return None

    class _QFrame(_Widget):
        StyledPanel = 1

        def setFrameShape(self, _shape):
            return None

    class _QAbstractItemView:
        ExtendedSelection = 1
        NoEditTriggers = 0

    class _QListView:
        IconMode = 1
        Adjust = 2
        Static = 3

    class _QSlider(_Widget):
        NoTicks = 0
        TicksBelow = 1
        TicksAbove = 2
        valueChanged = _SignalDescriptor()
        sliderPressed = _SignalDescriptor()
        sliderReleased = _SignalDescriptor()

        def __init__(self, _orientation=None, parent=None):
            super().__init__(parent)
            self._value = 0
            self._blocked = False

        def setRange(self, _min_value, _max_value):
            return None

        def setValue(self, value):
            self._value = value
            if not self._blocked:
                self.valueChanged.emit(value)

        def setTickInterval(self, _value):
            return None

        def setTickPosition(self, _value):
            return None

        def setSingleStep(self, _value):
            return None

        def setPageStep(self, _value):
            return None

        def setToolTip(self, _text):
            return None

        def value(self):
            return self._value

        def blockSignals(self, value):
            self._blocked = value

    class _QComboBox(_Widget):
        currentTextChanged = _SignalDescriptor()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._items = []
            self._text = ""
            self._blocked = False

        def addItems(self, items):
            self._items.extend(items)
            if not self._text and items:
                self._text = items[0]

        def setCurrentText(self, text):
            self._text = text
            if not self._blocked:
                self.currentTextChanged.emit(text)

        def setToolTip(self, _text):
            return None

        def currentText(self):
            return self._text

        def blockSignals(self, value):
            self._blocked = value

    class _QAbstractSpinBox:
        NoButtons = 0

    class _QSpinBox(_Widget):
        valueChanged = _SignalDescriptor()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._value = 0
            self._blocked = False
            self._line_edit = _QLineEdit()

        def setRange(self, _lo, _hi):
            return None

        def setValue(self, value):
            self._value = value
            if not self._blocked:
                self.valueChanged.emit(value)

        def value(self):
            return self._value

        def setSuffix(self, _suffix):
            return None

        def setAlignment(self, _alignment):
            return None

        def setButtonSymbols(self, _symbols):
            return None

        def setToolTip(self, _text):
            return None

        def lineEdit(self):
            return self._line_edit

        def blockSignals(self, value):
            self._blocked = value

    class _QGroupBox(_Widget):
        def __init__(self, title="", parent=None):
            super().__init__(parent)
            self.title = title

    class _QLabel(_Widget):
        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self.text = text

    class _QDialog(_Widget):
        Accepted = 1

    class _QPushButton(_Widget):
        clicked = _SignalDescriptor()
        customContextMenuRequested = _SignalDescriptor()

        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self.text = text
            self._icon = None

        def setFlat(self, _flat):
            return None

        def setIcon(self, icon):
            self._icon = icon

        def setIconSize(self, _size):
            return None

    class _QCheckBox(_Widget):
        toggled = _SignalDescriptor()

        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self.text = text
            self._checked = False
            self._icon = None

        def setChecked(self, value):
            value = bool(value)
            changed = value != self._checked
            self._checked = value
            if changed:
                self.toggled.emit(value)

        def isChecked(self):
            return self._checked

        def setIcon(self, icon):
            self._icon = icon

        def setIconSize(self, _size):
            return None

    class _QMenuBar(_Widget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._menus = []

        def addMenu(self, title):
            menu = _QMenu(self)
            menu.title = title
            self._menus.append(menu)
            return menu

    class _QSplitter(_Widget):
        def __init__(self, _orientation=None, parent=None):
            super().__init__(parent)
            self._widgets = []

        def setHandleWidth(self, _width):
            return None

        def addWidget(self, widget):
            self._widgets.append(widget)

        def setSizes(self, _sizes):
            return None

        def saveState(self):
            return b""

        def restoreState(self, _state):
            return True

    class _QMessageBox:
        Yes = 1
        No = 2

        @staticmethod
        def question(*_args, **_kwargs):
            return _QMessageBox.No

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

        @staticmethod
        def critical(*_args, **_kwargs):
            return None

        @staticmethod
        def information(*_args, **_kwargs):
            return None

        @staticmethod
        def about(*_args, **_kwargs):
            return None

    class _QInputDialog:
        @staticmethod
        def getText(*_args, **_kwargs):
            return "", False

    class _QFileDialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return "", ""

        @staticmethod
        def getOpenFileName(*_args, **_kwargs):
            return "", ""

    class _QSizePolicy:
        Expanding = 1

    class _QtWidgets:
        QApplication = _QApplication
        QWidget = _Widget
        QAction = _QAction
        QMenu = _QMenu
        QMenuBar = _QMenuBar
        QListWidget = _QListWidget
        QListWidgetItem = _QListWidgetItem
        QLineEdit = _QLineEdit
        QHBoxLayout = _QHBoxLayout
        QVBoxLayout = _QVBoxLayout
        QGridLayout = _QGridLayout
        QFrame = _QFrame
        QAbstractItemView = _QAbstractItemView
        QListView = _QListView
        QSlider = _QSlider
        QComboBox = _QComboBox
        QSpinBox = _QSpinBox
        QAbstractSpinBox = _QAbstractSpinBox
        QCheckBox = _QCheckBox
        QGroupBox = _QGroupBox
        QLabel = _QLabel
        QDialog = _QDialog
        QPushButton = _QPushButton
        QSplitter = _QSplitter
        QMessageBox = _QMessageBox
        QInputDialog = _QInputDialog
        QFileDialog = _QFileDialog
        QSizePolicy = _QSizePolicy

    return _QtCore, _QtGui, _QtWidgets, _SignalDescriptor, _slot, _QAction


try:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot
    from PySide2.QtWidgets import QAction  # PySide2: QAction lives in QtWidgets

    PYSIDE_VERSION = 2
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtCore import Signal, Slot
        from PySide6.QtGui import QAction  # PySide6: QAction moved to QtGui

        PYSIDE_VERSION = 6
    except ImportError:
        QtCore, QtGui, QtWidgets, Signal, Slot, QAction = _build_qt_test_stub()
        PYSIDE_VERSION = 0


# ------------------------------------------------------------------
# Maya detection
# ------------------------------------------------------------------

MAYA_AVAILABLE = "maya.cmds" in sys.modules or "maya" in sys.modules


def is_maya() -> bool:
    """Return True when running inside a Maya session."""
    return MAYA_AVAILABLE


def ensure_maya_mock() -> None:
    """Inject lightweight mock stubs for Maya modules into sys.modules.

    Call this at the top of any test module that imports code referencing
    ``maya.cmds`` or ``maya.api.OpenMaya`` so the imports succeed outside
    of a live Maya session.  Has no effect if Maya is already present.
    """
    global MAYA_AVAILABLE

    if MAYA_AVAILABLE:
        return

    from unittest.mock import MagicMock

    maya_mock = MagicMock()
    sys.modules.setdefault("maya", maya_mock)
    sys.modules.setdefault("maya.cmds", MagicMock())
    sys.modules.setdefault("maya.api", MagicMock())
    sys.modules.setdefault("maya.api.OpenMaya", MagicMock())
    sys.modules.setdefault("maya.OpenMayaUI", MagicMock())
    sys.modules.setdefault("maya.standalone", MagicMock())
    MAYA_AVAILABLE = True
