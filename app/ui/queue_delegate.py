"""The list pane's painted parts: queue rows, state marks, the product mark.

A row is two lines of text beside a state mark, with nothing around it. The
selected row is a quiet fill with a highlighter stroke across the file name.
The delegate fills its whole rect with an opaque color first, so whatever the
style painted behind the cell can never show through.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QLocale, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QWidget,
)

from app.core.queue_model import DisplayState, QueueItem, QueueTableModel, SourceKind
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.theme import Tokens, tokens_for

ROW_HEIGHT = 52
GLYPH_SIZE = 16
BRAND_MARK_SIZE = 20

_PADDING = 14
_GLYPH_GAP = 10
_COLUMN_GAP = 12
_NAME_PX = 13
_META_PX = 12
_STROKE_OVERHANG = 3
# One fixed column, wide enough for the label in every language.
_ACTION_WIDTH = 76
_ACTION_HEIGHT = 26
_BRIEF_ERROR_CHARS = 200

# markitdown names the attempt first and the actual problem after this.
_ATTEMPT_MESSAGE = re.compile(r"threw \w+ with message:\s*(.+)")
_SYSTEM_ERROR_NUMBER = re.compile(r"^\[(?:Errno|WinError) \d+\]\s*")

RETRY_STATES = {DisplayState.ERROR, DisplayState.SAVE_FAILED}


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


def current_tokens() -> Tokens:
    app = QApplication.instance()
    return tokens_for((app.property("themeName") if app is not None else None) or "light")


def brief_error(message: str) -> str:
    """The most specific single line of a conversion error."""
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[0]
    if line.endswith(":") and len(lines) > 1:
        line = lines[1].lstrip("- ")
    found = _ATTEMPT_MESSAGE.search(line)
    if found:
        line = found.group(1)
    line = _SYSTEM_ERROR_NUMBER.sub("", line)
    return line if len(line) <= _BRIEF_ERROR_CHARS else line[:_BRIEF_ERROR_CHARS].rstrip() + "…"


def row_status_text(item: QueueItem) -> str:
    """A row's status line. A problem names its reason where it is first seen."""
    state = item.display_state
    if state == DisplayState.ERROR and item.error_message.strip():
        return tr("status.failed_reason", reason=brief_error(item.error_message))
    if state == DisplayState.SAVE_FAILED:
        return tr("status.not_saved_reason", reason=brief_error(item.save_error))
    return tr(state.value)


def word_count(markdown: str | None) -> int:
    """Words in converted Markdown. Tokens with no letter or digit, such as
    `#`, `-`, `|` and `---`, are syntax rather than words."""
    return sum(1 for token in (markdown or "").split() if any(char.isalnum() for char in token))


def _words_text(markdown: str) -> str:
    count = word_count(markdown)
    locale = QLocale(QLocale.Language.Spanish if i18n_manager.language == LANG_ES else QLocale.Language.English)
    return tr("detail.words.one" if count == 1 else "detail.words.other", count=locale.toString(count))


def detail_status(item: QueueItem) -> str:
    """The detail header's line: what is real about this item's output."""
    state = item.display_state
    if state == DisplayState.SAVED:
        status = tr("status.saved_as", name=os.path.basename(item.saved_path))
    elif state == DisplayState.DONE:
        status = tr(state.value)
    elif state == DisplayState.SAVE_FAILED:
        return tr("status.save_failed_detail", error=brief_error(item.save_error))
    elif state == DisplayState.ERROR:
        return brief_error(item.error_message) or tr("preview.failed")
    elif state == DisplayState.CONVERTING:
        return tr("preview.converting")
    else:
        return tr("preview.pending")
    if item.markdown_result is None:
        return status
    return f"{status}, {_words_text(item.markdown_result)}"


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


# (singular key, plural key). Written out so every key stays greppable.
_FAILED = ("summary.failed.one", "summary.failed.other")
_NOT_SAVED = ("summary.not_saved.one", "summary.not_saved.other")
_READY = ("summary.ready.one", "summary.ready.other")
_CONVERTING = ("summary.converting.one", "summary.converting.other")
_WAITING = ("summary.waiting.one", "summary.waiting.other")
_ALL_SAVED = ("summary.all_saved.one", "summary.all_saved.other")


def _count_text(keys: tuple[str, str], count: int) -> str:
    return tr(keys[0] if count == 1 else keys[1], count=count)


def _join_counts(*parts: tuple[tuple[str, str], int]) -> str:
    return ", ".join(_count_text(keys, count) for keys, count in parts if count)


@dataclass(frozen=True)
class QueueSummary:
    headline: str
    detail: str
    glyph: str
    attention: bool


def queue_summary(items: list[QueueItem]) -> QueueSummary | None:
    """Answer "is it ready, and does anything need me?" from the real items."""
    if not items:
        return None
    states = Counter(item.display_state for item in items)
    total = len(items)
    failed = states[DisplayState.ERROR]
    not_saved = states[DisplayState.SAVE_FAILED]
    saved = states[DisplayState.SAVED]
    ready = saved + states[DisplayState.DONE]
    converting = states[DisplayState.CONVERTING]
    waiting = states[DisplayState.PENDING]

    if failed or not_saved:
        return QueueSummary(
            _join_counts((_FAILED, failed), (_NOT_SAVED, not_saved)),
            _join_counts((_READY, ready), (_CONVERTING, converting), (_WAITING, waiting)),
            "failed" if failed else "warning",
            True,
        )
    if saved == total:
        return QueueSummary(_count_text(_ALL_SAVED, total), "", "saved", False)
    return QueueSummary(
        tr("summary.ready_of", ready=ready, total=total),
        _join_counts((_CONVERTING, converting), (_WAITING, waiting)),
        "working" if converting or waiting else "converted",
        False,
    )


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
        """A problem row's tooltip is the whole message; the row can only cut it."""
        model = index.model()
        item = model.item_at(index.row()) if isinstance(model, QueueTableModel) else None
        if item is not None and item.display_state == DisplayState.ERROR and item.error_message:
            QToolTip.showText(event.globalPos(), item.error_message, view)
            return True
        if item is not None and item.display_state == DisplayState.SAVE_FAILED:
            QToolTip.showText(event.globalPos(), tr("tooltip.save_failed", error=item.save_error), view)
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

    def _status_parts(self, item, t) -> tuple[str, str]:
        state = item.display_state
        return tr(state.value), getattr(t, _STATE_STYLES[state].text)
