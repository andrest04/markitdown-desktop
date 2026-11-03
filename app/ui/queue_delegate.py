"""Queue rows.

A row is two lines of text beside a state mark, with nothing around it. The
selected row is a quiet fill with a highlighter stroke across the file name.
The delegate fills its whole rect with an opaque color first, so whatever the
style painted behind the cell can never show through.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)

from app.core.queue_model import (
    RETRY_STATES,
    DisplayState,
    QueueItem,
    QueueTableModel,
    SourceKind,
    row_status_text,
)
from app.i18n import tr
from app.ui.status_mark import GLYPH_SIZE, paint_status_glyph
from app.ui.theme import Tokens, current_tokens

ROW_HEIGHT = 52

_PADDING = 14
_GLYPH_GAP = 10
_COLUMN_GAP = 12
_NAME_PX = 13
_META_PX = 12
_STROKE_OVERHANG = 3
# One fixed column, wide enough for the label in every language.
_ACTION_WIDTH = 76
_ACTION_HEIGHT = 26
_TOOLTIP_DETAIL_CHARS = 600


@dataclass(frozen=True)
class StatusStyle:
    text: str  # theme token for the status line
    glyph_color: str  # theme token for the mark
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


def row_tooltip(item: QueueItem) -> str:
    """What a problem row cannot fit: its whole reason, the raw text, and the key."""
    state = item.display_state
    if state not in RETRY_STATES:
        return ""
    raw = item.error_message if state == DisplayState.ERROR else item.save_error
    raw = raw.strip()
    if len(raw) > _TOOLTIP_DETAIL_CHARS:
        raw = raw[:_TOOLTIP_DETAIL_CHARS].rstrip() + "…"
    return "\n".join(part for part in (row_status_text(item), raw, tr("row.retry_hint")) if part)


def retry_rect(cell: QRect, item: QueueItem) -> QRect | None:
    """Where a row's retry sits: one column, one pitch, only on rows that need it."""
    if item.display_state not in RETRY_STATES:
        return None
    return QRect(
        cell.right() - _PADDING - _ACTION_WIDTH + 1,
        cell.top() + (cell.height() - _ACTION_HEIGHT) // 2,
        _ACTION_WIDTH,
        _ACTION_HEIGHT,
    )


class QueueItemDelegate(QStyledItemDelegate):
    """Paint each queue row as a list line, not a spreadsheet cell or a card."""

    retry_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spin_angle = 0
        self._hover_action_row = -1

    @property
    def spin_angle(self) -> int:
        return self._spin_angle

    def advance_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def editorEvent(self, event, model, option, index) -> bool:
        item = model.item_at(index.row()) if isinstance(model, QueueTableModel) else None
        rect = retry_rect(option.rect, item) if item is not None else None
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove:
            self._track_action_hover(index.row() if rect and rect.contains(event.position().toPoint()) else -1, option)
        elif (
            event_type == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and rect is not None
            and rect.contains(event.position().toPoint())
        ):
            self.retry_requested.emit(index.row())
            return True
        return super().editorEvent(event, model, option, index)

    def _track_action_hover(self, row: int, option: QStyleOptionViewItem) -> None:
        if row == self._hover_action_row:
            return
        self._hover_action_row = row
        view = self.parent()
        if view is not None:
            view.viewport().update(option.rect)

    def helpEvent(self, event, view, option, index) -> bool:
        """A problem row's tooltip is the whole story; the row can only cut it."""
        model = index.model()
        item = model.item_at(index.row()) if isinstance(model, QueueTableModel) else None
        tooltip = row_tooltip(item) if item is not None else ""
        if tooltip:
            QToolTip.showText(event.globalPos(), tooltip, view)
            return True
        return super().helpEvent(event, view, option, index)

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

        t = current_tokens()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        fill = t.wash if selected else (t.hover if hovered else t.desk)

        painter.save()
        rect = option.rect
        painter.fillRect(rect, QColor(fill))

        style = status_style(item.display_state)

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
        glyph_rect = QRect(rect.left() + _PADDING, top + (line_height - GLYPH_SIZE) // 2, GLYPH_SIZE, GLYPH_SIZE)
        paint_status_glyph(painter, glyph_rect, style.glyph, getattr(t, style.glyph_color), fill, self._spin_angle)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        text_left = glyph_rect.right() + 1 + _GLYPH_GAP
        text_right = rect.right() - _PADDING

        action = retry_rect(rect, item)
        if action is not None:
            self._paint_retry(painter, action, meta_font, t, index.row())
            text_right = action.left() - _COLUMN_GAP

        type_label = self._type_label(item)
        name_right = text_right
        if type_label:
            type_width = meta_metrics.horizontalAdvance(type_label)
            painter.setFont(meta_font)
            painter.setPen(QColor(t.muted))
            painter.drawText(
                QRect(text_right - type_width + 1, top, type_width, line_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                type_label,
            )
            name_right = text_right - type_width - _COLUMN_GAP

        name_width = max(0, name_right - text_left + 1)
        name = name_metrics.elidedText(item.display_source(), Qt.TextElideMode.ElideMiddle, name_width)
        if selected:
            # A highlighter marks the words: flush with the line, a little past each end.
            painter.fillRect(
                QRect(
                    text_left - _STROKE_OVERHANG,
                    top,
                    name_metrics.horizontalAdvance(name) + 2 * _STROKE_OVERHANG,
                    line_height,
                ),
                QColor(t.mark),
            )
        painter.setFont(name_font)
        painter.setPen(QColor(t.on_mark if selected else t.ink))
        painter.drawText(
            QRect(text_left, top, name_width, line_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )

        status_width = max(0, text_right - text_left + 1)
        painter.setFont(meta_font)
        painter.setPen(QColor(getattr(t, style.text)))
        painter.drawText(
            QRect(text_left, top + line_height + 2, status_width, meta_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            meta_metrics.elidedText(row_status_text(item), Qt.TextElideMode.ElideRight, status_width),
        )

        if focused:
            ring = QPen(QColor(t.ink), 2)
            ring.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        painter.restore()

    def _paint_retry(self, painter: QPainter, rect: QRect, font: QFont, t: Tokens, row: int) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(t.edge), 1))
        painter.setBrush(QColor(t.wash_strong) if row == self._hover_action_row else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        painter.setFont(font)
        painter.setPen(QColor(t.ink))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("button.retry_row"))
        painter.restore()

    def _type_label(self, item) -> str:
        """Only links get a type: a file name already ends in its own."""
        if item.kind != SourceKind.URL or not item.detected_type:
            return ""
        return tr(item.detected_type)
