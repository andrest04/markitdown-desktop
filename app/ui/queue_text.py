"""The words that describe an item and the queue as a whole, as plain functions."""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass

from PySide6.QtCore import QLocale

from app.core.queue_model import DisplayState, QueueItem, failure_reason_text
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager


def word_count(markdown: str | None) -> int:
    """Words in converted Markdown. Tokens with no letter or digit, such as
    `#`, `-`, `|` and `---`, are syntax rather than words."""
    return sum(1 for token in (markdown or "").split() if any(char.isalnum() for char in token))


def _saved_word_count(item: QueueItem) -> int | None:
    """Counted once per saved text: that text cannot change, and it may be very long."""
    if item.saved_word_count is None and item.saved_text is not None:
        item.saved_word_count = word_count(item.saved_text)
    return item.saved_word_count


def _words_text(count: int) -> str:
    locale = QLocale(QLocale.Language.Spanish if i18n_manager.language == LANG_ES else QLocale.Language.English)
    return tr("detail.words.one" if count == 1 else "detail.words.other", count=locale.toString(count))


def detail_status(item: QueueItem) -> str:
    """The detail header's line: what is real about this item's output."""
    state = item.display_state
    if state == DisplayState.SAVED:
        status = tr("status.saved_as", name=os.path.basename(item.saved_path))
        count = _saved_word_count(item)
    elif state == DisplayState.DONE:
        status = tr(state.value)
        count = None if item.markdown_result is None else word_count(item.markdown_result)
    elif state == DisplayState.SAVE_FAILED:
        return tr("status.save_failed_detail", error=tr(item.save_error_reason.value))
    elif state == DisplayState.ERROR:
        reason = failure_reason_text(item)
        return reason[:1].upper() + reason[1:] if reason else tr("preview.failed")
    elif state == DisplayState.CONVERTING:
        return tr("preview.converting")
    else:
        return tr("preview.pending")
    return status if count is None else f"{status}, {_words_text(count)}"


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
