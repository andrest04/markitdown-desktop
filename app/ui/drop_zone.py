"""Primary drop / browse / paste surface used by the main window."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr

FORMAT_CHIPS = ("PDF", "Word", "Excel", "PPT", "Image", "Audio", "HTML", "ZIP", "URL")

EMPTY_HEIGHT = 320
FILLED_HEIGHT = 96


class _FileDropFilter(QObject):
    """Forwards file drops on other panes to the drop zone that owns it."""

    def __init__(self, drop_zone: DropZone):
        super().__init__(drop_zone)
        self._drop_zone = drop_zone

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.DragEnter:
            return self._drop_zone._begin_drag(event)
        if event_type == QEvent.Type.DragLeave:
            self._drop_zone.set_drag_active(False)
        elif event_type == QEvent.Type.Drop:
            self._drop_zone._finish_drop(event)
            return True
        return False


class DropZone(QWidget):
    """Drop target for files and folders. Browse is an explicit button.

    Centered content when the queue is empty; shrinks to a slim bar
    once items exist so the queue can take over. The canvas accepts
    drops but is not a giant click-to-open hit target.
    """

    def __init__(self, on_paths_dropped, on_click=None, on_url=None, on_folder=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_paths_dropped = on_paths_dropped
        self._on_click = on_click
        self._on_url = on_url
        self._on_folder = on_folder
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumHeight(EMPTY_HEIGHT)
        self._prominent = True
        self.setProperty("prominent", True)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(12)

        self._title = QLabel(tr("dropzone.title.empty"))
        self._title.setObjectName("DropZoneTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        title_font = self._title.font()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)

        self._hint = QLabel(tr("dropzone.hint.empty"))
        self._hint.setObjectName("DropZoneHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)

        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("DropZoneUrl")
        self.url_edit.setPlaceholderText(tr("url.placeholder"))
        self.url_edit.setCursor(Qt.CursorShape.IBeamCursor)
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._submit_url)
        self.url_edit.setMinimumHeight(36)

        self.add_url_btn = QPushButton(tr("button.add_url"))
        self.add_url_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_url_btn.clicked.connect(self._submit_url)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.add_url_btn)

        self._browse_row = QWidget()
        self._browse_row.setCursor(Qt.CursorShape.ArrowCursor)
        browse_layout = QHBoxLayout(self._browse_row)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse_btn = QPushButton(tr("dropzone.browse"))
        self.browse_btn.setObjectName("secondary")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._browse)
        self.folder_btn = QPushButton(tr("dropzone.add_folder"))
        self.folder_btn.setObjectName("secondary")
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.clicked.connect(self._add_folder)
        browse_layout.addWidget(self.browse_btn)
        browse_layout.addWidget(self.folder_btn)

        self._chips = QWidget()
        self._chips.setCursor(Qt.CursorShape.ArrowCursor)
        chips_layout = QHBoxLayout(self._chips)
        chips_layout.setContentsMargins(0, 8, 0, 0)
        chips_layout.setSpacing(6)
        chips_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip_labels: list[QLabel] = []
        for name in FORMAT_CHIPS:
            chip = QLabel(name)
            chip.setObjectName("FormatChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            chips_layout.addWidget(chip)
            self._chip_labels.append(chip)

        self._save_note = QLabel(tr("dropzone.saves_to"))
        self._save_note.setObjectName("DropZoneSaveNote")
        self._save_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._save_note.setWordWrap(True)

        root.addStretch(1)
        root.addWidget(self._title)
        root.addWidget(self._hint)
        root.addSpacing(8)
        root.addLayout(url_row)
        root.addWidget(self._browse_row)
        root.addWidget(self._chips)
        root.addWidget(self._save_note)
        root.addStretch(1)

        self.setProperty("dragActive", False)
        self._drop_filter = _FileDropFilter(self)

    def set_prominent(self, prominent: bool) -> None:
        """Switch between the big empty-queue look and a slim bar."""
        self._prominent = prominent
        self.setProperty("prominent", prominent)
        self.setMinimumHeight(EMPTY_HEIGHT if prominent else FILLED_HEIGHT)
        self.setMaximumHeight(16777215 if prominent else FILLED_HEIGHT)
        self.style().unpolish(self)
        self.style().polish(self)
        layout = self.layout()
        layout.setContentsMargins(*(28, 28, 28, 24) if prominent else (16, 10, 16, 10))
        layout.setStretch(0, 1 if prominent else 0)
        layout.setStretch(layout.count() - 1, 1 if prominent else 0)
        self._title.setText(tr("dropzone.title.empty") if prominent else tr("dropzone.title.filled"))
        title_font = self._title.font()
        title_font.setPointSize(18 if prominent else 12)
        self._title.setFont(title_font)
        self._hint.setText(tr("dropzone.hint.empty"))
        self._hint.setVisible(prominent)
        self._browse_row.setVisible(prominent)
        self._chips.setVisible(prominent)
        self._save_note.setVisible(prominent)
        self._save_note.setText(tr("dropzone.saves_to"))
        self.url_edit.setPlaceholderText(tr("url.placeholder"))
        self.add_url_btn.setText(tr("button.add_url"))
        self.browse_btn.setText(tr("dropzone.browse"))
        self.folder_btn.setText(tr("dropzone.add_folder"))

    def retranslate(self) -> None:
        self.set_prominent(self._prominent)

    def accept_drops_on(self, *widgets: QWidget) -> None:
        """Treat a file drop on any of `widgets` as a drop on this zone."""
        for widget in widgets:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self._drop_filter)

    def set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _browse(self) -> None:
        if self._on_click is not None:
            self._on_click()

    def _add_folder(self) -> None:
        if self._on_folder is not None:
            self._on_folder()

    def _submit_url(self) -> None:
        if self._on_url is not None:
            self._on_url()

    def _begin_drag(self, event) -> bool:
        """Accept a drag that carries URLs; returns whether it was accepted."""
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return False
        event.acceptProposedAction()
        self.set_drag_active(True)
        return True

    def _finish_drop(self, event) -> None:
        self.set_drag_active(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._on_paths_dropped(paths)
        event.acceptProposedAction()

    def dragEnterEvent(self, event):
        self._begin_drag(event)

    def dragLeaveEvent(self, event):
        self.set_drag_active(False)

    def dropEvent(self, event):
        self._finish_drop(event)
