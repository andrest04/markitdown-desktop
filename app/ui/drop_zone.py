"""Add surface: the empty-window instruction, and the link field once items exist."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.ui.theme import set_tier

FILLED_HEIGHT = 58
_URL_ROW_WIDTH = 560
_EMPTY_MARGINS = (56, 0, 56, 0)
_FILLED_MARGINS = (12, 12, 12, 12)


class _FileDropFilter(QObject):
    """Forwards file drops on other panes to the drop zone that owns it."""

    def __init__(self, drop_zone: DropZone):
        super().__init__(drop_zone)
        self._drop_zone = drop_zone

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.DragLeave:
            self._drop_zone.set_drag_active(False)
            return False
        if event_type not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        # Anything but files, such as text dragged inside the editor, is not ours.
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return False
        if event_type == QEvent.Type.DragEnter:
            return self._drop_zone._begin_drag(event)
        if event_type == QEvent.Type.DragMove:
            event.acceptProposedAction()
            return True
        self._drop_zone._finish_drop(event)
        return True


class DropZone(QWidget):
    """Drop target for files and folders, with no box drawn around it.

    The whole window accepts drops, through `accept_drops_on()`. With an empty
    queue this is the instruction and the ways to add something. Once items
    exist only the link field stays, above the list.
    """

    drag_active_changed = Signal(bool)

    def __init__(self, on_paths_dropped, on_click=None, on_url=None, on_folder=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_paths_dropped = on_paths_dropped
        self._on_click = on_click
        self._on_url = on_url
        self._on_folder = on_folder
        self.setAcceptDrops(True)
        self._prominent = True
        self.setProperty("prominent", True)
        self.setProperty("dragActive", False)
        self._drop_filter = _FileDropFilter(self)

        self._title = QLabel(tr("dropzone.title.empty"))
        self._title.setObjectName("DropZoneTitle")

        self._hint = QLabel(tr("dropzone.saves_to"))
        self._hint.setObjectName("DropZoneHint")
        self._hint.setWordWrap(True)

        self.browse_btn = QPushButton(tr("button.add_files"))
        set_tier(self.browse_btn, "primary")
        self.browse_btn.clicked.connect(self._browse)
        self.folder_btn = QPushButton(tr("button.add_folder"))
        self.folder_btn.clicked.connect(self._add_folder)
        browse_row = QHBoxLayout()
        browse_row.setSpacing(8)
        browse_row.addWidget(self.browse_btn)
        browse_row.addWidget(self.folder_btn)
        browse_row.addStretch(1)

        self._url_label = QLabel(tr("dropzone.url_label"))
        self._url_label.setObjectName("DropZoneLabel")

        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("DropZoneUrl")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._submit_url)
        self._url_label.setBuddy(self.url_edit)

        self.add_url_btn = QPushButton(tr("button.add_url"))
        self.add_url_btn.clicked.connect(self._submit_url)

        self._url_row = QWidget()
        url_layout = QHBoxLayout(self._url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)
        url_layout.addWidget(self.url_edit, 1)
        url_layout.addWidget(self.add_url_btn)

        self._formats = QLabel(tr("dropzone.formats"))
        self._formats.setObjectName("DropZoneFormats")
        self._formats.setWordWrap(True)

        # Only the link row survives into the slim state, so everything else
        # lives in two containers that hide together with their spacing.
        self._intro = QWidget()
        intro_layout = QVBoxLayout(self._intro)
        intro_layout.setContentsMargins(0, 0, 0, 0)
        intro_layout.setSpacing(0)
        intro_layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignLeft)
        intro_layout.addSpacing(12)
        intro_layout.addWidget(self._hint)
        intro_layout.addSpacing(24)
        intro_layout.addLayout(browse_row)
        intro_layout.addSpacing(32)
        intro_layout.addWidget(self._url_label)
        intro_layout.addSpacing(6)

        self._outro = QWidget()
        outro_layout = QVBoxLayout(self._outro)
        outro_layout.setContentsMargins(0, 16, 0, 0)
        outro_layout.addWidget(self._formats)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.addStretch(2)
        self._layout.addWidget(self._intro)
        self._layout.addWidget(self._url_row)
        self._layout.addWidget(self._outro)
        self._layout.addStretch(3)

        self.setTabOrder(self.browse_btn, self.folder_btn)
        self.setTabOrder(self.folder_btn, self.url_edit)
        self.setTabOrder(self.url_edit, self.add_url_btn)
        self._apply_prominence()

    def set_prominent(self, prominent: bool) -> None:
        """Switch between the empty-window instruction and the slim link row."""
        self._prominent = prominent
        self._apply_prominence()

    def _apply_prominence(self) -> None:
        prominent = self._prominent
        self.setProperty("prominent", prominent)
        self.style().unpolish(self)
        self.style().polish(self)

        self._layout.setContentsMargins(*(_EMPTY_MARGINS if prominent else _FILLED_MARGINS))
        self.setMaximumHeight(16777215 if prominent else FILLED_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding if prominent else QSizePolicy.Policy.Fixed,
        )
        self._intro.setVisible(prominent)
        self._outro.setVisible(prominent)
        self._url_row.setMaximumWidth(_URL_ROW_WIDTH if prominent else 16777215)
        self.retranslate()

    def retranslate(self) -> None:
        self._title.setText(tr("dropzone.title.empty"))
        self._hint.setText(tr("dropzone.saves_to"))
        self._url_label.setText(tr("dropzone.url_label"))
        self._formats.setText(tr("dropzone.formats"))
        self.url_edit.setAccessibleName(tr("dropzone.url_label"))
        self.url_edit.setPlaceholderText(tr("url.placeholder" if self._prominent else "url.placeholder.filled"))
        self.add_url_btn.setText(tr("button.add_url"))
        self.browse_btn.setText(tr("button.add_files"))
        self.folder_btn.setText(tr("button.add_folder"))

    def accept_drops_on(self, *widgets: QWidget) -> None:
        """Treat a file drop on any of `widgets` as a drop on this zone."""
        for widget in widgets:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self._drop_filter)

    def set_drag_active(self, active: bool) -> None:
        if bool(self.property("dragActive")) == active:
            return
        self.setProperty("dragActive", active)
        self.drag_active_changed.emit(active)

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
