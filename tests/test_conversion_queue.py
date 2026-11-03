"""The convert-then-save flow, exercised without a MainWindow."""
from __future__ import annotations

import ast
import threading
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThreadPool
from qt_support import QtTestCase, pump_until, settle

from app.core.converter import ConversionOptions
from app.core.queue_model import ItemStatus, QueueItem, QueueTableModel, SourceKind

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_item(name: str, source: str | None = None) -> QueueItem:
    return QueueItem(source=source or f"/somewhere/{name}", kind=SourceKind.FILE, display_name=name)


class ConversionQueueTestCase(QtTestCase):
    def setUp(self) -> None:
        super().setUp()
        from app.core.conversion_queue import ConversionQueue

        self.model = QueueTableModel()
        self.queue = ConversionQueue(self.model)
        self.events: list[tuple] = []
        self.queue.item_started.connect(lambda item: self.events.append(("started", item.display_name)))
        self.queue.item_finished.connect(lambda item: self.events.append(("finished", item.display_name)))
        self.queue.item_failed.connect(lambda item, msg: self.events.append(("failed", item.display_name, msg)))
        self.queue.item_saved.connect(lambda item, path: self.events.append(("saved", item.display_name)))
        self.queue.item_save_failed.connect(lambda item, err: self.events.append(("save_failed", item.display_name, err)))
        self.queue.progress_changed.connect(lambda done, total: self.events.append(("progress", done, total)))
        self.queue.batch_finished.connect(lambda: self.events.append(("batch_finished",)))

    def enqueue(self, *items: QueueItem) -> int:
        for item in items:
            self.model.add_item(item)
        return self.queue.enqueue(list(items), ConversionOptions())


class FlowTests(ConversionQueueTestCase):
    def test_convert_then_save_runs_without_a_window(self):
        item = make_item("a.txt")
        self.assertEqual(self.enqueue(item), 1)
        self.converter.release_all()
        settle()

        self.assertEqual(item.status, ItemStatus.DONE)
        self.assertEqual(item.markdown_result, "# converted a.txt")
        self.assertEqual(Path(item.saved_path).parent, self.downloads)
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertEqual(
            self.events,
            [
                ("progress", 0, 1),
                ("started", "a.txt"),
                ("saved", "a.txt"),
                ("finished", "a.txt"),
                ("progress", 1, 1),
                ("batch_finished",),
            ],
        )

    def test_explicit_downloads_dir_wins(self):
        from app.core.conversion_queue import ConversionQueue

        target = self.tmp / "elsewhere"
        queue = ConversionQueue(self.model, downloads_dir=target)
        item = make_item("a.txt")
        self.model.add_item(item)
        queue.enqueue([item], ConversionOptions())
        self.converter.release_all()
        settle()

        self.assertEqual(Path(item.saved_path).parent, target)
        self.assertEqual(self.downloaded_names(), [])

    def test_saved_names_never_collide_and_are_utf8(self):
        self.downloads.mkdir()
        (self.downloads / "ñ.md").write_text("existing", encoding="utf-8")
        item = make_item("ñ.txt")
        self.enqueue(item)
        self.converter.release_all()
        settle()

        self.assertEqual(self.downloaded_names(), ["ñ (1).md", "ñ.md"])
        self.assertEqual((self.downloads / "ñ.md").read_text(encoding="utf-8"), "existing")
        self.assertEqual(Path(item.saved_path).read_bytes(), "# converted ñ.txt".encode())

    def test_conversion_failure_is_reported_and_does_not_stop_the_batch(self):
        self.converter.failures["bad.txt"] = "boom"
        bad, good = make_item("bad.txt"), make_item("good.txt")
        self.enqueue(bad, good)
        self.converter.release_all()
        settle()

        self.assertEqual(bad.status, ItemStatus.ERROR)
        self.assertEqual(good.status, ItemStatus.DONE)
        self.assertIn(("failed", "bad.txt", "boom"), self.events)
        self.assertEqual(self.events.count(("batch_finished",)), 1)

    def test_save_failure_stays_done_with_save_error(self):
        item = make_item("a.txt")
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("disk full")):
            self.enqueue(item)
            self.converter.release_all()
            settle()

        self.assertEqual(item.status, ItemStatus.DONE)
        self.assertEqual(item.save_error, "disk full")
        self.assertIn(("save_failed", "a.txt", "disk full"), self.events)
        self.assertIn(("finished", "a.txt"), self.events)

    def test_removed_item_saves_nothing_and_still_counts(self):
        item = make_item("a.txt")
        self.enqueue(item)
        pump_until(lambda: self.converter.call_count() == 1)
        self.model.clear()
        self.converter.release_all()
        settle()

        self.assertEqual(self.downloaded_names(), [])
        self.assertNotIn(("finished", "a.txt"), self.events)
        self.assertEqual(self.events[-2:], [("progress", 1, 1), ("batch_finished",)])

    def test_enqueue_ignores_items_already_in_flight(self):
        item = make_item("a.txt")
        self.assertEqual(self.enqueue(item), 1)
        self.assertEqual(self.queue.enqueue([item], ConversionOptions()), 0)
        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_workers_receive_the_options_they_were_enqueued_with(self):
        item = make_item("a.txt")
        options = ConversionOptions(enable_plugins=True)
        self.model.add_item(item)
        self.queue.enqueue([item], options)
        self.converter.release_all()
        settle()
        self.assertIs(self.converter.options_seen[0], options)


class RemovedItemTests(ConversionQueueTestCase):
    """Removing an item cancels what has not started and silences what has."""

    def setUp(self) -> None:
        super().setUp()
        pool = QThreadPool.globalInstance()
        previous = pool.maxThreadCount()
        pool.setMaxThreadCount(1)
        self.addCleanup(pool.setMaxThreadCount, previous)

    def _remove(self, *items: QueueItem) -> None:
        self.model.remove_rows([self.model.row_of(item) for item in items])
        self.queue.discard(list(items))

    def test_a_queued_worker_never_runs_and_leaves_the_total(self):
        running, queued = make_item("running.txt"), make_item("queued.txt")
        self.enqueue(running, queued)
        pump_until(lambda: self.converter.call_count() == 1)

        self._remove(queued)
        self.assertEqual(self.events[-1], ("progress", 0, 1))

        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("queued.txt"), 0)
        self.assertEqual(self.downloaded_names(), ["running.md"])
        self.assertEqual(self.events[-2:], [("progress", 1, 1), ("batch_finished",)])

    def test_a_queued_item_can_be_cancelled_after_others_completed(self):
        first, second, third = make_item("a.txt"), make_item("b.txt"), make_item("c.txt")
        self.enqueue(first, second, third)
        pump_until(lambda: self.converter.call_count() == 1)
        self.converter.release("a.txt")
        pump_until(lambda: ("progress", 1, 3) in self.events and self.converter.call_count() == 2)

        self._remove(third)
        self.assertEqual(self.events[-1], ("progress", 1, 2))

        self.converter.release_all()
        settle()
        self.assertEqual(self.events[-2:], [("progress", 2, 2), ("batch_finished",)])

    def test_cancelling_everything_left_finishes_the_batch(self):
        # Something else fills the pool's one slot, so nothing of ours can start.
        slot_taken, slot_free = threading.Event(), threading.Event()
        self.addCleanup(slot_free.set)

        def hold_the_slot():
            slot_taken.set()
            slot_free.wait(10)

        QThreadPool.globalInstance().start(hold_the_slot)
        self.assertTrue(slot_taken.wait(5))

        item = make_item("a.txt")
        self.enqueue(item)
        self._remove(item)

        self.assertEqual(self.events[-1], ("batch_finished",))
        slot_free.set()
        settle()
        self.assertEqual(self.converter.call_count(), 0)

    def test_a_running_item_keeps_counting_but_stays_silent(self):
        item = make_item("a.txt")
        self.enqueue(item)
        pump_until(lambda: self.converter.call_count() == 1)

        self._remove(item)
        self.converter.release_all()
        settle()

        self.assertEqual(self.downloaded_names(), [])
        self.assertNotIn(("saved", "a.txt"), self.events)
        self.assertNotIn(("finished", "a.txt"), self.events)
        self.assertEqual(self.events[-2:], [("progress", 1, 1), ("batch_finished",)])

    def test_a_removed_item_that_fails_reports_nothing(self):
        self.converter.failures["a.txt"] = "boom"
        item = make_item("a.txt")
        self.enqueue(item)
        pump_until(lambda: self.converter.call_count() == 1)

        self._remove(item)
        self.converter.release_all()
        settle()

        self.assertFalse([event for event in self.events if event[0] == "failed"])
        self.assertEqual(self.events[-2:], [("progress", 1, 1), ("batch_finished",)])

    def test_discarding_something_the_queue_never_saw_changes_nothing(self):
        self.queue.discard([make_item("a.txt")])
        self.assertEqual(self.events, [])

    def test_a_finished_item_can_be_discarded_safely(self):
        item = make_item("a.txt")
        self.enqueue(item)
        self.converter.release_all()
        settle()
        before = list(self.events)
        self._remove(item)
        self.assertEqual(self.events, before)


class ThreadingTests(ConversionQueueTestCase):
    def test_conversion_runs_off_and_auto_save_runs_on_the_gui_thread(self):
        from app.core.converter import auto_save_markdown

        save_threads: list[threading.Thread] = []
        signal_threads: list[threading.Thread] = []

        def recording_save(*args, **kwargs):
            save_threads.append(threading.current_thread())
            return auto_save_markdown(*args, **kwargs)

        for signal in (self.queue.item_started, self.queue.item_finished):
            signal.connect(lambda _item: signal_threads.append(threading.current_thread()))

        with mock.patch("app.core.conversion_queue.auto_save_markdown", recording_save):
            self.enqueue(make_item("a.txt"))
            self.converter.release_all()
            settle()

        main = threading.main_thread()
        self.assertNotEqual(self.converter.threads[0], main)
        self.assertEqual(save_threads, [main])
        self.assertEqual(signal_threads, [main, main])


class BoundaryTests(unittest.TestCase):
    @staticmethod
    def _imports(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_conversion_queue_never_translates(self):
        source = REPO_ROOT / "app" / "core" / "conversion_queue.py"
        self.assertNotIn("app.i18n", self._imports(source))
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("tr", calls)

    def test_only_converter_imports_markitdown(self):
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "app").rglob("*.py")
            if path.name != "converter.py"
            and any(name.split(".")[0] == "markitdown" for name in self._imports(path))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
