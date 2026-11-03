"""State marks: one silhouette per item state, so a state survives without color."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import current_tokens

GLYPH_SIZE = 16


def _check_path(box: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(box.left() + box.width() * 0.08, box.top() + box.height() * 0.54)
    path.lineTo(box.left() + box.width() * 0.38, box.top() + box.height() * 0.84)
    path.lineTo(box.left() + box.width() * 0.92, box.top() + box.height() * 0.18)
    return path


def paint_status_glyph(painter: QPainter, rect: QRect, glyph: str, color: str, knockout: str, angle: int = 0) -> None:
    """Draw a state mark. Each one has its own silhouette and weight, so they
    read apart in greyscale: dots, an arc, half a disc, a bare check, an open
    triangle, and a solid square that is the heaviest because it needs you.
    `knockout` is the row fill, for the cross cut into the square.
    """
    box = QRectF(rect).adjusted(1, 1, -1, -1)
    unit = box.width() / 14
    round_pen = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    solid = QColor(color)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if glyph == "waiting":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        radius = 1.25 * unit
        for x in (0.14, 0.5, 0.86):
            painter.drawEllipse(QPointF(box.left() + box.width() * x, box.center().y()), radius, radius)
    elif glyph == "working":
        painter.setPen(QPen(solid, 2 * unit, *round_pen))
        painter.drawArc(box.adjusted(unit, unit, -unit, -unit), -angle * 16, 270 * 16)
    elif glyph == "converted":
        painter.setPen(QPen(solid, 1.5 * unit, *round_pen))
        inner = box.adjusted(unit, unit, -unit, -unit)
        painter.drawEllipse(inner)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawPie(inner, 90 * 16, 180 * 16)
    elif glyph == "saved":
        painter.setPen(QPen(solid, 2.2 * unit, *round_pen))
        painter.drawPath(_check_path(box))
    elif glyph == "failed":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawRoundedRect(box, 2 * unit, 2 * unit)
        painter.setPen(QPen(QColor(knockout), 2 * unit, *round_pen))
        inset = box.width() * 0.3
        inner = box.adjusted(inset, inset, -inset, -inset)
        painter.drawLine(inner.topLeft(), inner.bottomRight())
        painter.drawLine(inner.topRight(), inner.bottomLeft())
    elif glyph == "warning":
        pen = QPen(solid, 1.5 * unit, *round_pen)
        painter.setPen(pen)
        triangle = QPainterPath()
        triangle.moveTo(box.center().x(), box.top() + unit)
        triangle.lineTo(box.right() - 0.5 * unit, box.bottom() - unit)
        triangle.lineTo(box.left() + 0.5 * unit, box.bottom() - unit)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        x = box.center().x()
        painter.drawLine(QPointF(x, box.top() + box.height() * 0.40), QPointF(x, box.top() + box.height() * 0.62))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawEllipse(QPointF(x, box.top() + box.height() * 0.76), 0.85 * unit, 0.85 * unit)
    painter.restore()


class StatusMark(QWidget):
    """A state mark outside the list, so a summary speaks the rows' language."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(GLYPH_SIZE, GLYPH_SIZE)
        self._glyph = "waiting"
        self._attention = False
        self._angle = 0

    def set_glyph(self, glyph: str, attention: bool) -> None:
        self._glyph = glyph
        self._attention = attention
        self.update()

    def set_angle(self, angle: int) -> None:
        self._angle = angle
        if self._glyph == "working":
            self.update()

    def paintEvent(self, event) -> None:
        t = current_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = t.danger if self._attention else t.ink
        paint_status_glyph(painter, self.rect(), self._glyph, color, t.desk, self._angle)
