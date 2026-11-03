"""The product mark."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from app.ui.theme import Tokens, current_tokens

BRAND_MARK_SIZE = 20


def paint_brand_mark(painter: QPainter, rect: QRect, t: Tokens) -> None:
    """The product in one picture: a page of text with one line highlighted."""
    box = QRectF(rect)
    unit = box.width() / 20
    left = box.left() + 4 * unit
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(t.ink))
    painter.drawRoundedRect(box, 4 * unit, 4 * unit)
    # The stroke runs edge to edge and is thicker than the lines, the way a marker is.
    painter.setBrush(QColor(t.mark))
    painter.drawRect(QRectF(box.left(), box.top() + 7.5 * unit, box.width(), 5 * unit))
    painter.setBrush(QColor(t.primary_fg))
    painter.drawRect(QRectF(left, box.top() + 4 * unit, 12 * unit, 1.5 * unit))
    painter.drawRect(QRectF(left, box.top() + 14.5 * unit, 8 * unit, 1.5 * unit))
    painter.restore()


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(BRAND_MARK_SIZE, BRAND_MARK_SIZE)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_brand_mark(painter, self.rect(), current_tokens())
