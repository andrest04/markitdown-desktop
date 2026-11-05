"""Runs queue items through the convert-then-auto-save contract.

The window only starts work and reacts to the signals below, so this flow can
run and be tested without any widget. Nothing here translates text: signals
carry raw values and the receiver decides what to show.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from app.core.converter import (
    ConversionOptions,
    ConversionWorker,
    auto_save_markdown,
    classify_save_error,
)
from app.core.queue_model import FailureReason, QueueItem, QueueTableModel


class ConversionQueue(QObject):
    """Dispatches one worker per item and applies the results to the model.

    Worker signals connect to bound slots of this QObject, so Qt queues them
    onto the GUI thread. That is where items change and files get written;
    `unique_download_path` checks then writes, so saves must not run in parallel.
    """

    item_started = Signal(object)
    item_finished = Signal(object)
    item_failed = Signal(object, str)
    item_saved = Signal(object, str)
    item_save_failed = Signal(object, str)
    progress_changed = Signal(int, int)  # completed, total
    batch_finished = Signal()

    def __init__(self, model: QueueTableModel, downloads_dir: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._model = model
        self._downloads_dir = downloads_dir
        self._completed_count = 0
        self._total_count = 0
        # Dispatched but not yet finished. Status only changes once a worker
        # actually starts, so it cannot guard against double dispatch.
        self._in_flight: dict[QueueItem, ConversionWorker] = {}

    def enqueue(self, items: list[QueueItem], options: ConversionOptions) -> int:
        """Start a worker for each item not already in flight; returns how many."""
        to_start = [item for item in items if item not in self._in_flight]
        if not to_start:
            return 0

        # Totals accumulate across overlapping batches and reset only when idle.
        if not self._in_flight:
            self._completed_count = 0
            self._total_count = 0
        self._total_count += len(to_start)

        pool = QThreadPool.globalInstance()
        for item in to_start:
            worker = ConversionWorker(item, options)
            self._in_flight[item] = worker
            worker.signals.started.connect(self._on_started)
            worker.signals.finished.connect(self._on_finished)
            worker.signals.failed.connect(self._on_failed)
            pool.start(worker)

        self.progress_changed.emit(self._completed_count, self._total_count)
        return len(to_start)

    def unfinished_count(self) -> int:
        """Results still to come. A removed item's result has nowhere to go."""
        return sum(self._model.row_of(item) >= 0 for item in self._in_flight)

    def cancel_unstarted(self) -> None:
        """Cancel every worker that has not started, for closing. See `discard`."""
        self.discard(list(self._in_flight))

    def discard(self, items: list[QueueItem]) -> None:
        """Forget items just removed from the model.

        A worker that has not started is cancelled and leaves the total. A
        running one cannot be interrupted, because markitdown blocks: it keeps
        counting until it returns, and its result goes nowhere, since the item
        no longer has a row.
        """
        pool = QThreadPool.globalInstance()
        cancelled = [item for item in items if item in self._in_flight and self._in_flight[item].take_from(pool)]
        if not cancelled:
            return
        for item in cancelled:
            del self._in_flight[item]
        self._total_count -= len(cancelled)
        if self._in_flight:
            self.progress_changed.emit(self._completed_count, self._total_count)
        else:
            self.batch_finished.emit()

    @Slot(object)
    def _on_started(self, item: QueueItem) -> None:
        row = self._model.row_of(item)
        if row >= 0:
            item.mark_converting()
            self._model.refresh_row(row)
            self.item_started.emit(item)

    @Slot(object, str)
    def _on_finished(self, item: QueueItem, markdown_text: str) -> None:
        # An item removed from the queue meanwhile saves nothing.
        row = self._model.row_of(item)
        if row >= 0:
            item.mark_converted(markdown_text)
            self._auto_save(item)
            self._model.refresh_row(row)
            self.item_finished.emit(item)
        self._advance_progress(item)
        if row >= 0 and item.save_error:
            # Last, for the same reason as a failed conversion below.
            self.item_save_failed.emit(item, item.save_error)

    @Slot(object, object, str)
    def _on_failed(self, item: QueueItem, reason: FailureReason, message: str) -> None:
        # An item removed from the queue meanwhile has no failure to report.
        row = self._model.row_of(item)
        if row >= 0:
            item.mark_failed(message, reason)
            self._model.refresh_row(row)
        self._advance_progress(item)
        if row >= 0:
            # Last, so the failure stays visible instead of "batch complete".
            self.item_failed.emit(item, message)

    def _auto_save(self, item: QueueItem) -> None:
        """Write a freshly converted item straight to Downloads (the whole
        point of the app being "drop it and it's done" -- no manual export
        step required)."""
        try:
            saved_path = auto_save_markdown(item, item.markdown_result or "", self._downloads_dir)
        except OSError as exc:
            item.mark_save_failed(str(exc), classify_save_error(exc))
        else:
            item.mark_saved(str(saved_path))
            self.item_saved.emit(item, str(saved_path))

    def _advance_progress(self, item: QueueItem) -> None:
        self._in_flight.pop(item, None)
        self._completed_count += 1
        self.progress_changed.emit(self._completed_count, self._total_count)
        if not self._in_flight:
            self.batch_finished.emit()
