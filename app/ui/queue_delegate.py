"""Custom list-style painter for conversion queue rows."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from app.core.queue_model import DisplayState, QueueTableModel
from app.i18n import tr
from app.ui.theme import tokens_for

ROW_HEIGHT = 68
RADIUS = 10

# Per state: theme token for the status line, then the pill's translation key
# and its foreground/background theme tokens.
_STATE_STYLES = {
    DisplayState.PENDING: ("muted", "status.pill.pending", "muted", "sunken"),
    DisplayState.CONVERTING: ("mark", "status.pill.converting", "mark", "mark_tint"),
    DisplayState.DONE: ("muted", "status.pill.pending", "muted", "sunken"),
    DisplayState.SAVED: ("mark", "status.pill.saved", "mark", "mark_tint"),
    DisplayState.SAVE_FAILED: ("danger", "status.pill.save_failed", "danger", "danger_tint"),
    DisplayState.ERROR: ("danger", "status.pill.error", "danger", "danger_tint"),
}


class QueueItemDelegate(QStyledItemDelegate):
    """Paint each queue row as a quiet activity line, not a spreadsheet cell."""

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

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        fill = QColor(t.mark_tint if selected else (t.sunken if hovered else t.elevated))
        painter.setPen(QPen(QColor(t.mark if selected else t.rule), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        name_font = QFont(option.font)
        name_font.setPointSize(11)
        name_font.setWeight(QFont.Weight.DemiBold)
        meta_font = QFont(option.font)
        meta_font.setPointSize(9)
        pill_font = QFont(option.font)
        pill_font.setPointSize(9)
        pill_font.setWeight(QFont.Weight.DemiBold)

        type_label = tr(item.detected_type) if item.detected_type else ""
        status_text, status_color = self._status_parts(item, t)
        pill_text, pill_fg, pill_bg = self._pill_parts(item, t)

        pill_metrics = QFontMetrics(pill_font)
        pill_width = pill_metrics.horizontalAdvance(pill_text) + 18
        pill_height = 22
        pill_rect = QRect(
            rect.right() - 12 - pill_width,
            rect.center().y() - pill_height // 2,
            pill_width,
            pill_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pill_bg))
        painter.drawRoundedRect(pill_rect, 11, 11)
        painter.setFont(pill_font)
        painter.setPen(QColor(pill_fg))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, pill_text)

        text_rect = rect.adjusted(14, 10, -20 - pill_width, -10)
        name = QFontMetrics(name_font).elidedText(
            item.display_source(),
            Qt.TextElideMode.ElideMiddle,
            text_rect.width(),
        )

        painter.setFont(name_font)
        painter.setPen(QColor(t.ink))
        painter.drawText(
            QRect(text_rect.left(), text_rect.top(), text_rect.width(), 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )

        meta = " · ".join(part for part in (type_label, status_text) if part)
        painter.setFont(meta_font)
        painter.setPen(QColor(status_color))
        painter.drawText(
            QRect(text_rect.left(), text_rect.top() + 22, text_rect.width(), 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(meta_font).elidedText(meta, Qt.TextElideMode.ElideRight, text_rect.width()),
        )

        painter.restore()

    def _status_parts(self, item, t) -> tuple[str, str]:
        state = item.display_state
        color, _, _, _ = _STATE_STYLES[state]
        return tr(state.value), getattr(t, color)

    def _pill_parts(self, item, t) -> tuple[str, str, str]:
        _, pill_key, foreground, background = _STATE_STYLES[item.display_state]
        return tr(pill_key), getattr(t, foreground), getattr(t, background)
