"""Drag-and-drop / click-to-browse target used by the main window."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

from app.i18n import tr

EMPTY_HEIGHT = 260
FILLED_HEIGHT = 90


class DropZone(QWidget):
    """Drag-and-drop target for files and folders; also click-to-browse.

    Big and centered when the queue is empty (the primary, dominant UI
    surface); shrinks to a slim bar once items exist so the queue table
    can take over.
    """

    def __init__(self, on_paths_dropped, on_click=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_paths_dropped = on_paths_dropped
        self._on_click = on_click
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(EMPTY_HEIGHT)
        self._prominent = True

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(61, 123, 245, 170))
        self.setGraphicsEffect(self._shadow)

        self._hover_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        self._label = QLabel(tr("dropzone.empty"))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        font = self._label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setWeight(QFont.Weight.DemiBold)
        self._label.setFont(font)
        layout.addWidget(self._label)
        self.setProperty("dragActive", False)

    def set_prominent(self, prominent: bool) -> None:
        """Switch between the big "empty queue" look and a slim bar."""
        self._prominent = prominent
        self.setMinimumHeight(EMPTY_HEIGHT if prominent else FILLED_HEIGHT)
        self._label.setText(tr("dropzone.empty") if prominent else tr("dropzone.filled"))

    def retranslate(self) -> None:
        self.set_prominent(self._prominent)

    def mousePressEvent(self, event) -> None:
        if self._on_click is not None and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._animate_shadow(28)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_shadow(0)
        super().leaveEvent(event)

    def _animate_shadow(self, target: int) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._shadow.blurRadius())
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._on_paths_dropped(paths)
        event.acceptProposedAction()
