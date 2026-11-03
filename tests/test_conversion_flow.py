"""End-to-end queue behavior, driven through the window with a stubbed converter."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QThreadPool
from qt_support import WindowTestCase, pump_until, settle

from app.core.queue_model import ItemStatus, QueueItem, SourceKind
from app.i18n import tr


class ItemIdentityTests(WindowTestCase):
    def test_removing_an_earlier_row_applies_result_to_the_right_item(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)
        pump_until(lambda: self.item_named("b.txt").status == ItemStatus.CONVERTING)

        self.window.table_view.selectRow(0)
        self.window.action_remove_selected()
        self.converter.release_all()
        settle()

        survivor = self.item_named("b.txt")
        self.assertEqual(survivor.status, ItemStatus.DONE)
        self.assertEqual(survivor.markdown_result, "# converted b.txt")
        self.assertEqual(self.downloaded_names(), ["b.md"])

    def test_failure_after_removal_marks_the_right_item(self):
        self.converter.failures["b.txt"] = "boom"
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)

        self.window.table_view.selectRow(0)
        self.window.action_remove_selected()
        self.converter.release_all()
        settle()

        survivor = self.item_named("b.txt")
        self.assertEqual(survivor.status, ItemStatus.ERROR)
        self.assertEqual(survivor.error_message, "boom")
        self.assertIsNone(survivor.markdown_result)
        self.assertEqual(self.downloaded_names(), [])

    def test_removed_item_saves_nothing_but_progress_still_advances(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)

        self.window.table_view.selectRow(0)
        self.window.action_remove_selected()
        self.converter.release("a.txt")
        pump_until(lambda: self.window.progress_bar.value() == 1)

        self.assertEqual(self.progress_state(), (1, 2, True))
        self.assertEqual(self.downloaded_names(), [])

        self.converter.release("b.txt")
        settle()
        self.assertFalse(self.progress_state()[2])
        self.assertEqual(self.downloaded_names(), ["b.md"])

    def test_clearing_the_queue_mid_conversion_saves_nothing(self):
        self.add_sources("a.txt")
        self.wait_started(1)

        self.window.action_clear_all()
        self.converter.release_all()
        settle()

        self.assertEqual(self.window.model.items(), [])
        self.assertEqual(self.downloaded_names(), [])
        self.assertFalse(self.progress_state()[2])

    def _one_worker_at_a_time(self) -> None:
        pool = QThreadPool.globalInstance()
        previous = pool.maxThreadCount()
        pool.setMaxThreadCount(1)
        self.addCleanup(pool.setMaxThreadCount, previous)

    def test_removing_a_queued_row_cancels_its_worker(self):
        self._one_worker_at_a_time()
        self.add_sources("a.txt", "b.txt")
        self.wait_started(1)

        self.window.table_view.selectRow(self.window.model.row_of(self.item_named("b.txt")))
        self.window.action_remove_selected()
        self.assertEqual(self.progress_state(), (0, 1, True))

        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("b.txt"), 0)
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertFalse(self.progress_state()[2])

    def test_clearing_the_list_cancels_every_queued_worker(self):
        self._one_worker_at_a_time()
        self.add_sources("a.txt", "b.txt", "c.txt")
        self.wait_started(1)

        self.window.action_clear_all()
        self.assertEqual(self.progress_state(), (0, 1, True))

        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count(), 1)
        self.assertEqual(self.downloaded_names(), [])
        self.assertFalse(self.progress_state()[2])

    def test_a_removed_items_failure_stays_out_of_the_status_bar(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)

        self.window.table_view.selectRow(0)
        self.window.action_remove_selected()
        self.converter.release("a.txt")
        pump_until(lambda: self.window.progress_bar.value() == 1)

        self.assertNotIn("boom", self.window.status_bar.currentMessage())

    def test_items_with_identical_fields_stay_distinct(self):
        first = QueueItem(source="same", kind=SourceKind.FILE, display_name="same")
        twin = QueueItem(source="same", kind=SourceKind.FILE, display_name="same")
        self.window.model.add_item(first)
        self.assertEqual(self.window.model.row_of(first), 0)
        self.assertEqual(self.window.model.row_of(twin), -1)


class OverlappingBatchTests(WindowTestCase):
    def test_second_batch_does_not_report_completion_early(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)
        self.converter.release("a.txt")
        pump_until(lambda: self.window.progress_bar.value() == 1)

        self.add_sources("c.txt")
        self.wait_started(3)
        self.assertEqual(self.progress_state(), (1, 3, True))

        self.converter.release("b.txt")
        pump_until(lambda: self.window.progress_bar.value() == 2)
        self.assertEqual(self.progress_state(), (2, 3, True))
        self.assertNotEqual(self.window.status_bar.currentMessage(), tr("status.batch_complete"))

        self.converter.release("c.txt")
        settle()
        self.assertFalse(self.progress_state()[2])
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.batch_complete"))

    def test_counters_reset_once_idle(self):
        self.add_sources("a.txt", "b.txt")
        self.converter.release_all()
        settle()
        self.assertFalse(self.progress_state()[2])

        self.converter.hold_all()
        self.add_sources("c.txt")
        self.assertEqual(self.progress_state(), (0, 1, True))

    def test_status_bar_shows_saved_path_then_batch_complete(self):
        self.add_sources("a.txt")
        self.converter.release_all()
        settle()
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.batch_complete"))

    def test_failure_message_outlives_batch_complete(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release_all()
        settle()
        self.assertEqual(
            self.window.status_bar.currentMessage(),
            tr("status.conversion_failed", message="boom"),
        )

    def test_first_finished_item_is_selected_when_nothing_is(self):
        self.add_sources("a.txt")
        self.window.table_view.clearSelection()
        self.converter.release_all()
        settle()
        self.assertEqual(self.window._selected_row(), 0)
        self.assertEqual(self.window.raw_view.toPlainText(), "# converted a.txt")

    def test_retry_with_nothing_to_start_keeps_the_running_bar(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)
        pump_until(lambda: self.item_named("a.txt").status == ItemStatus.CONVERTING)
        self.window.table_view.selectRow(0)

        self.window.action_convert_selected()

        self.assertEqual(self.progress_state(), (0, 2, True))


class DoubleDispatchTests(WindowTestCase):
    def test_converting_again_before_the_worker_starts_is_ignored(self):
        self.add_sources("a.txt")
        self.window.table_view.selectRow(0)

        self.window.action_convert_selected()

        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_double_retry_starts_one_worker(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR)
        self.window.table_view.selectRow(0)

        self.window.action_convert_selected()
        self.window.action_convert_selected()

        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 2)

    def test_retry_is_allowed_after_the_previous_run_finished(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR)
        settle()
        del self.converter.failures["a.txt"]
        self.window.table_view.selectRow(0)

        self.window.action_convert_selected()
        self.converter.release("a.txt")
        pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE)
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(self.item_named("a.txt").error_message, "")


if __name__ == "__main__":
    unittest.main()
