"""Custom list painter for conversion queue rows.

A row is two lines of text beside a status glyph, with nothing around it. The
selected row is a square highlighter band across the whole cell. The delegate
fills its whole rect with an opaque color first, so whatever the style painted
behind the cell can never show through.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from app.core.queue_model import DisplayState, QueueTableModel, SourceKind
from app.i18n import tr
from app.ui.theme import tokens_for

ROW_HEIGHT = 52

_PADDING = 14
_GLYPH_SIZE = 16
_GLYPH_GAP = 10
_COLUMN_GAP = 12
_NAME_PX = 13
_META_PX = 12

# On the highlighter every status color swaps to its readable counterpart.
_ON_MARK = {"ink": "on_mark", "muted": "on_mark_muted", "danger": "on_mark_danger"}


@dataclass(frozen=True)
class StatusStyle:
    text: str  # theme token for the status line
    glyph_color: str  # theme token for the glyph
    glyph: str  # shape, so a state survives without color


_STATE_STYLES = {
    DisplayState.PENDING: StatusStyle("muted", "muted", "waiting"),
    DisplayState.CONVERTING: StatusStyle("muted", "ink", "working"),
    DisplayState.DONE: StatusStyle("muted", "ink", "converted"),
    DisplayState.SAVED: StatusStyle("muted", "ink", "saved"),
    DisplayState.SAVE_FAILED: StatusStyle("danger", "danger", "warning"),
    DisplayState.ERROR: StatusStyle("danger", "danger", "failed"),
}


def status_style(state: DisplayState) -> StatusStyle:
    return _STATE_STYLES[state]


def _check_path(box: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(box.left() + box.width() * 0.28, box.top() + box.height() * 0.52)
    path.lineTo(box.left() + box.width() * 0.44, box.top() + box.height() * 0.68)
    path.lineTo(box.left() + box.width() * 0.72, box.top() + box.height() * 0.34)
    return path


def paint_status_glyph(painter: QPainter, rect: QRect, glyph: str, color: str, knockout: str, angle: int = 0) -> None:
    """Draw a status shape. `knockout` is the row fill, for marks cut into a solid shape."""
    box = QRectF(rect).adjusted(1, 1, -1, -1)
    round_pen = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    outline = QPen(QColor(color), 1.5, *round_pen)
    cut = QPen(QColor(knockout), 1.8, *round_pen)
    solid = QColor(color)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if glyph == "waiting":
        painter.setPen(outline)
        painter.drawEllipse(box)
    elif glyph == "working":
        painter.setPen(QPen(QColor(color), 2, *round_pen))
        painter.drawArc(box, -angle * 16, 270 * 16)
    elif glyph == "converted":
        painter.setPen(outline)
        painter.drawEllipse(box)
        painter.drawPath(_check_path(box))
    elif glyph == "saved":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawEllipse(box)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(cut)
        painter.drawPath(_check_path(box))
    elif glyph == "failed":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawEllipse(box)
        painter.setPen(cut)
        inset = box.width() * 0.32
        inner = box.adjusted(inset, inset, -inset, -inset)
        painter.drawLine(inner.topLeft(), inner.bottomRight())
        painter.drawLine(inner.topRight(), inner.bottomLeft())
    elif glyph == "warning":
        triangle = QPainterPath()
        triangle.moveTo(box.center().x(), box.top())
        triangle.lineTo(box.right(), box.bottom())
        triangle.lineTo(box.left(), box.bottom())
        triangle.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(solid)
        painter.drawPath(triangle)
        painter.setPen(cut)
        x = box.center().x()
        painter.drawLine(QPointF(x, box.top() + box.height() * 0.38), QPointF(x, box.top() + box.height() * 0.64))
        painter.drawPoint(QPointF(x, box.top() + box.height() * 0.84))
    painter.restore()


class QueueItemDelegate(QStyledItemDelegate):
    """Paint each queue row as a list line, not a spreadsheet cell or a card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spin_angle = 0

    def advance_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.column() != 0:
            return
        model = index.model()
        if not isinstance(model, QueueTableModel):
            super().paint(painter, option, index)
            return
        item = model.item_at(index.row())
        if item is None:
            return

        theme_name = "light"
        app = QApplication.instance()
        if app is not None:
            theme_name = app.property("themeName") or "light"
        t = tokens_for(theme_name)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        fill = t.mark if selected else (t.wash if hovered else t.desk)
        ink = t.on_mark if selected else t.ink
        muted = t.on_mark_muted if selected else t.muted

        painter.save()
        rect = option.rect
        painter.fillRect(rect, QColor(fill))

        status_text, status_color = self._status_parts(item, t, selected=selected)
        style = status_style(item.display_state)
        glyph_token = _ON_MARK[style.glyph_color] if selected else style.glyph_color

        name_font = QFont(option.font)
        name_font.setPixelSize(_NAME_PX)
        name_font.setWeight(QFont.Weight.DemiBold)
        meta_font = QFont(option.font)
        meta_font.setPixelSize(_META_PX)
        name_metrics = QFontMetrics(name_font)
        meta_metrics = QFontMetrics(meta_font)

        line_height = name_metrics.height()
        meta_height = meta_metrics.height()
        block = line_height + 2 + meta_height
        top = rect.top() + (rect.height() - block) // 2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glyph_rect = QRect(rect.left() + _PADDING, top + (line_height - _GLYPH_SIZE) // 2, _GLYPH_SIZE, _GLYPH_SIZE)
        paint_status_glyph(painter, glyph_rect, style.glyph, getattr(t, glyph_token), fill, self._spin_angle)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        text_left = glyph_rect.right() + 1 + _GLYPH_GAP
        text_right = rect.right() - _PADDING

        type_label = self._type_label(item)
        name_right = text_right
        if type_label:
            type_width = meta_metrics.horizontalAdvance(type_label)
            painter.setFont(meta_font)
            painter.setPen(QColor(muted))
            painter.drawText(
                QRect(text_right - type_width + 1, top, type_width, line_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                type_label,
            )
            name_right = text_right - type_width - _COLUMN_GAP

        name_width = max(0, name_right - text_left + 1)
        painter.setFont(name_font)
        painter.setPen(QColor(ink))
        painter.drawText(
            QRect(text_left, top, name_width, line_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name_metrics.elidedText(item.display_source(), Qt.TextElideMode.ElideMiddle, name_width),
        )

        status_width = max(0, text_right - text_left + 1)
        painter.setFont(meta_font)
        painter.setPen(QColor(status_color))
        painter.drawText(
            QRect(text_left, top + line_height + 2, status_width, meta_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            meta_metrics.elidedText(status_text, Qt.TextElideMode.ElideRight, status_width),
        )

        if focused:
            ring = QPen(QColor(ink), 2)
            ring.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        painter.restore()

    def _type_label(self, item) -> str:
        """Only links get a type: a file name already ends in its own."""
        if item.kind != SourceKind.URL or not item.detected_type:
            return ""
        return tr(item.detected_type)

    def _status_parts(self, item, t, selected: bool = False) -> tuple[str, str]:
        state = item.display_state
        token = _STATE_STYLES[state].text
        return tr(state.value), getattr(t, _ON_MARK[token] if selected else token)
