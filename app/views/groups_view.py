"""
Left panel — shape outliner with search and context menu.
"""
from app.compat import QtCore, QtGui, QtWidgets, QAction

from app.models.search import search_shapes


class OutlinerWidget(QtWidgets.QWidget):
    """Browseable list of control shape names with live search."""

    shape_selected = QtCore.Signal(str)      # emits shape label on single click
    shape_renamed = QtCore.Signal(str, str)  # emits (old_key, new_label)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_items = []

        self.create_widgets()
        self.create_actions()
        self.create_layout()
        self.create_connections()

    def create_actions(self):
        self.replace_action = QAction("Replace Control", self)
        self.reset_color_action = QAction("Reset Color", self)
        self.duplicate_action = QAction("Duplicate", self)
        self.remove_action = QAction("Remove", self)
        self.context_menu = QtWidgets.QMenu(self)
        self.context_menu.addAction(self.replace_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.reset_color_action)
        self.context_menu.addAction(self.duplicate_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.remove_action)

    def create_widgets(self):
        self.search_line = QtWidgets.QLineEdit()
        self.search_line.setPlaceholderText("Search...")
        self.search_line.setClearButtonEnabled(True)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def create_layout(self):
        search_row = QtWidgets.QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(self.search_line)

        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        inner = QtWidgets.QVBoxLayout(frame)
        inner.setContentsMargins(2, 2, 2, 2)
        inner.addLayout(search_row)
        inner.addWidget(self.list_widget)

        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(frame)

    def create_connections(self):
        self.search_line.textChanged.connect(self._on_search_changed)
        self.list_widget.currentTextChanged.connect(self.shape_selected)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.itemChanged.connect(self._on_item_renamed)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    # Public API — full load
    # ------------------------------------------------------------------

    def populate(self, shape_labels: dict) -> None:
        """Load {key: label} mapping into the list."""
        self._all_items = list(shape_labels.items())
        self._refresh(self._all_items)

    def selected_key(self) -> str | None:
        """Return the shape key for the currently selected item."""
        item = self.list_widget.currentItem()
        if not item:
            return None
        return item.data(QtCore.Qt.UserRole)

    def selected_keys(self) -> list:
        """Return all selected shape keys."""
        return [item.data(QtCore.Qt.UserRole)
                for item in self.list_widget.selectedItems()
                if item.data(QtCore.Qt.UserRole)]

    # ------------------------------------------------------------------
    # Public API — granular updates
    # ------------------------------------------------------------------

    def add_shape_item(self, key: str, label: str) -> None:
        """Append one shape without rebuilding the full list."""
        self._all_items.append((key, label))
        query = self.search_line.text()
        if not query or query.lower() in label.lower():
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.list_widget.addItem(item)

    def remove_shape_items(self, keys: list) -> None:
        """Remove shapes by key without rebuilding the full list."""
        key_set = set(keys)
        self._all_items = [(k, l) for k, l in self._all_items if k not in key_set]
        for i in range(self.list_widget.count() - 1, -1, -1):
            item = self.list_widget.item(i)
            if item and item.data(QtCore.Qt.UserRole) in key_set:
                self.list_widget.takeItem(i)

    def rename_shape_item(self, old_key: str, new_key: str, new_label: str) -> None:
        """Update key and label of one item in-place."""
        self._all_items = [
            (new_key, new_label) if k == old_key else (k, l)
            for k, l in self._all_items
        ]
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(QtCore.Qt.UserRole) == old_key:
                self.list_widget.blockSignals(True)
                item.setData(QtCore.Qt.UserRole, new_key)
                item.setText(new_label)
                self.list_widget.blockSignals(False)
                break

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        labels = [lbl for _, lbl in self._all_items]
        filtered = set(search_shapes(labels, text))
        matched = [(k, l) for k, l in self._all_items if l in filtered]
        self._refresh(matched)

    def _reset(self) -> None:
        self.search_line.clear()
        self._refresh(self._all_items)

    def _refresh(self, items: list) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for key, label in items:
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _on_item_double_clicked(self, item) -> None:
        self.list_widget.editItem(item)

    def _on_item_renamed(self, item) -> None:
        old_key = item.data(QtCore.Qt.UserRole)
        new_label = item.text().strip()
        if not old_key:
            return
        if not new_label:
            # Revert
            for key, lbl in self._all_items:
                if key == old_key:
                    item.setText(lbl)
                    break
            return
        # Check if actually changed
        for key, lbl in self._all_items:
            if key == old_key:
                if lbl == new_label:
                    return
                break
        self.shape_renamed.emit(old_key, new_label)

    def _show_context_menu(self, pos) -> None:
        self.context_menu.exec_(self.list_widget.mapToGlobal(pos))
