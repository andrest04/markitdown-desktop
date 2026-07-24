"""Queue data model backing the conversion table view."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.i18n import tr


class ItemStatus(Enum):
    """Values are translation KEYS (not display text) so the view can call
    tr() at display time -- switching language mid-session then updates
    every row already in the queue, not just newly-added ones."""

    PENDING = "status.pending"
    CONVERTING = "status.converting"
    DONE = "status.done"
    ERROR = "status.error"


class SourceKind(Enum):
    FILE = "File"
    URL = "URL"


@dataclass
class QueueItem:
    """A single entry in the conversion queue.

    For FILE items, `source` is an absolute local path.
    For URL items, `source` is the raw URL string.
    """

    source: str
    kind: SourceKind
    display_name: str
    detected_type: str = ""
    status: ItemStatus = ItemStatus.PENDING
    error_message: str = ""
    markdown_result: str | None = None
    # Per-item conversion overrides (extension/mimetype/charset hints)
    extension_override: str = ""
    mimetype_override: str = ""
    charset_override: str = ""
    # Result of the automatic save-to-Downloads step (set after conversion).
    saved_path: str = ""
    save_error: str = ""

    def display_source(self) -> str:
        return self.display_name


COLUMN_NAME = 0
COLUMN_TYPE = 1
COLUMN_STATUS = 2
COLUMN_COUNT = 3

_HEADER_KEYS = ["column.name", "column.type", "column.status"]


class QueueTableModel(QAbstractTableModel):
    """Table model exposing the list of QueueItem objects to a QTableView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[QueueItem] = []

    # -- Basic Qt model API -------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008 -- standard Qt model API signature
        if parent.isValid():
            return 0
        return len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008 -- standard Qt model API signature
        if parent.isValid():
            return 0
        return COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return tr(_HEADER_KEYS[section])
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COLUMN_NAME:
                return item.display_source()
            if col == COLUMN_TYPE:
                return tr(item.detected_type) if item.detected_type else "?"
            if col == COLUMN_STATUS:
                if item.status == ItemStatus.DONE and item.saved_path:
                    return tr("status.done_saved")
                if item.status == ItemStatus.DONE and item.save_error:
                    return tr("status.done_save_failed")
                return tr(item.status.value)
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COLUMN_STATUS and item.status == ItemStatus.ERROR:
                return item.error_message
            if col == COLUMN_STATUS and item.status == ItemStatus.DONE and item.saved_path:
                return tr("tooltip.saved_to", path=item.saved_path)
            if col == COLUMN_STATUS and item.status == ItemStatus.DONE and item.save_error:
                return tr("tooltip.save_failed", error=item.save_error)
            if col == COLUMN_NAME:
                return item.source
            return None

        return None

    # -- Queue management -----------------------------------------------
    def items(self) -> list[QueueItem]:
        return self._items

    def item_at(self, row: int) -> QueueItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def add_item(self, item: QueueItem) -> None:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()

    def remove_rows(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._items[row]
                self.endRemoveRows()

    def clear(self) -> None:
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            top_left = self.index(row, 0)
            bottom_right = self.index(row, COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def row_of(self, item: QueueItem) -> int:
        try:
            return self._items.index(item)
        except ValueError:
            return -1

    def source_exists(self, source: str) -> bool:
        return any(existing.source == source for existing in self._items)

    def retranslate(self) -> None:
        """Re-emit header/data-changed so headers and status text (which are
        resolved through tr() at display time) redraw in the new language."""
        if self._items:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._items) - 1, COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)
