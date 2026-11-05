"""Queue data model backing the conversion table view."""
from __future__ import annotations

import os
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


class DisplayState(Enum):
    """What an item means to the user, derived from status + save outcome.

    Values are translation KEYS, for the same reason as ItemStatus. Read it
    through `QueueItem.display_state`; never store it.
    """

    PENDING = "status.pending"
    CONVERTING = "status.converting"
    DONE = "status.done"
    SAVED = "status.done_saved"
    SAVE_FAILED = "status.done_save_failed"
    ERROR = "status.error"


class FailureReason(Enum):
    """Why a conversion or a save failed, as far as the app can tell.

    Values are translation KEYS, for the same reason as ItemStatus: library text
    cannot be translated, so `converter.py` sorts failures into these and the
    raw text stays alongside as detail.
    """

    UNSUPPORTED_FORMAT = "error.unsupported_format"
    MISSING_DEPENDENCY = "error.missing_dependency"
    UNREADABLE_FILE = "error.unreadable_file"
    FILE_NOT_FOUND = "error.file_not_found"
    PERMISSION_DENIED = "error.permission_denied"
    NETWORK = "error.network"
    NO_TEXT = "error.no_text"
    GENERIC = "error.generic"
    DISK_FULL = "error.disk_full"
    SAVE_GENERIC = "error.save_generic"


class SourceKind(Enum):
    FILE = "File"
    URL = "URL"


def detect_type_label(source: str, kind: SourceKind) -> str:
    """Best-effort, cheap type label for the queue table (no conversion)."""
    if kind == SourceKind.URL:
        lowered = source.lower()
        if "youtube.com" in lowered or "youtu.be" in lowered:
            return "YouTube"
        return "type.webpage"
    ext = os.path.splitext(source)[1].lower()
    return ext.lstrip(".").upper() if ext else "type.file"


@dataclass(eq=False)
class QueueItem:
    """A single entry in the conversion queue.

    For FILE items, `source` is an absolute local path.
    For URL items, `source` is the raw URL string.

    Compared and hashed by identity (`eq=False`): each entry is its own
    object, which is what lets workers and `row_of()` find it after the
    rows around it have changed.
    """

    source: str
    kind: SourceKind
    display_name: str
    detected_type: str = ""
    status: ItemStatus = ItemStatus.PENDING
    error_message: str = ""  # raw library text, for the detail pane
    error_reason: FailureReason = FailureReason.GENERIC
    markdown_result: str | None = None
    # Per-item conversion overrides (extension/mimetype/charset hints)
    extension_override: str = ""
    mimetype_override: str = ""
    charset_override: str = ""
    # Result of the automatic save-to-Downloads step (set after conversion).
    saved_path: str = ""
    saved_text: str | None = None  # what that file holds; edits change only markdown_result
    save_error: str = ""  # raw OS text
    save_error_reason: FailureReason = FailureReason.SAVE_GENERIC

    @classmethod
    def from_path(cls, path: str) -> QueueItem:
        abs_path = os.path.abspath(path)
        return cls(
            source=abs_path,
            kind=SourceKind.FILE,
            display_name=os.path.basename(abs_path),
            detected_type=detect_type_label(abs_path, SourceKind.FILE),
        )

    @classmethod
    def from_url(cls, url: str) -> QueueItem:
        return cls(
            source=url,
            kind=SourceKind.URL,
            display_name=url,
            detected_type=detect_type_label(url, SourceKind.URL),
        )

    def display_source(self) -> str:
        return self.display_name

    @property
    def display_state(self) -> DisplayState:
        if self.status == ItemStatus.PENDING:
            return DisplayState.PENDING
        if self.status == ItemStatus.CONVERTING:
            return DisplayState.CONVERTING
        if self.status == ItemStatus.ERROR:
            return DisplayState.ERROR
        if self.saved_path:
            return DisplayState.SAVED
        if self.save_error:
            return DisplayState.SAVE_FAILED
        return DisplayState.DONE

    def mark_converting(self) -> None:
        self.status = ItemStatus.CONVERTING

    def mark_converted(self, markdown_text: str) -> None:
        self.status = ItemStatus.DONE
        self.markdown_result = markdown_text
        self.error_message = ""

    def mark_failed(self, message: str, reason: FailureReason = FailureReason.GENERIC) -> None:
        """A failed retry keeps `saved_path`: the earlier file still exists."""
        self.status = ItemStatus.ERROR
        self.error_message = message
        self.error_reason = reason

    def mark_saved(self, path: str) -> None:
        self.saved_path = str(path)
        self.saved_text = self.markdown_result
        self.save_error = ""

    def mark_save_failed(self, error: str, reason: FailureReason = FailureReason.SAVE_GENERIC) -> None:
        """The conversion itself succeeded, so the status stays DONE."""
        self.saved_path = ""
        self.saved_text = None
        self.save_error = str(error)
        self.save_error_reason = reason


RETRY_STATES = {DisplayState.ERROR, DisplayState.SAVE_FAILED}


def failure_reason_text(item: QueueItem) -> str:
    """A failed item's reason in the current language, or "" when nothing is known."""
    if item.error_reason == FailureReason.GENERIC and not item.error_message.strip():
        return ""
    return tr(item.error_reason.value)


def row_status_text(item: QueueItem) -> str:
    """A row's status line. A problem names its reason where it is first seen."""
    state = item.display_state
    if state == DisplayState.ERROR and failure_reason_text(item):
        return tr("status.failed_reason", reason=failure_reason_text(item))
    if state == DisplayState.SAVE_FAILED:
        return tr("status.not_saved_reason", reason=tr(item.save_error_reason.value))
    return tr(state.value)


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
                return tr(item.display_state.value)
            return None

        if col != COLUMN_NAME:
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.source
        # The delegate paints a row's status, which a screen reader cannot see.
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{item.display_source()}, {row_status_text(item)}"
        if role == Qt.ItemDataRole.AccessibleDescriptionRole and item.display_state in RETRY_STATES:
            return tr("row.retry_hint")
        return None

    # -- Queue management -----------------------------------------------
    def items(self) -> list[QueueItem]:
        return self._items

    def item_at(self, row: int) -> QueueItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def add_item(self, item: QueueItem) -> int:
        """Append `item` and return its row."""
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()
        return row

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
