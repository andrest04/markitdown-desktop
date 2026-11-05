"""New work clears the last batch's message, and held keys cannot unselect a new row."""
from __future__ import annotations

from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from qt_support import WindowTestCase, process_events, pump_until, settle

from app.core.queue_model import DisplayState, QueueItem
from app.i18n import tr


class BatchMessageTests(WindowTestCase):
    def finish_a_batch(self):
        self.add_sources("a.txt")
        self.converter.release_all()
        settle()
        self.converter.hold_all()
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.batch_complete"))

    def test_adding_a_link_clears_it(self):
        self.finish_a_batch()
        self.window.url_edit.setText("https://example.com")
        self.window.action_add_url()
        self.assertEqual(self.window.status_bar.currentMessage(), "")

    def test_adding_files_replaces_it(self):
        self.finish_a_batch()
        self.add_sources("b.txt")
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.added_files", count=1))

    def test_converting_again_clears_it(self):
        self.finish_a_batch()
        self.window.conversion_queue.enqueue([self.item_named("a.txt")], self.window.conversion_options)
        self.assertEqual(self.window.status_bar.currentMessage(), "")

    def test_a_batch_with_problems_clears_too(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release_all()
        settle()
        self.converter.hold_all()
        self.assertNotEqual(self.window.status_bar.currentMessage(), "")
        self.window._start_conversion([0])
        self.assertEqual(self.window.status_bar.currentMessage(), "")

    def test_joining_a_running_batch_leaves_the_message_alone(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        self.window.status_bar.showMessage("something else")
        self.window.conversion_queue.enqueue([QueueItem.from_path(self.make_source("b.txt"))], self.window.conversion_options)
        self.assertEqual(self.window.status_bar.currentMessage(), "something else")

    def test_a_mixed_retry_still_reports_its_save(self):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("no")):
            self.add_sources("a.txt")
            self.converter.release("a.txt")
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVE_FAILED))
        self.converter.failures["b.txt"] = "boom"
        self.add_sources("b.txt")
        self.converter.release("b.txt")
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").error_message == "boom"))
        settle()
        del self.converter.failures["b.txt"]

        self.window._start_conversion([0, 1])

        self.assertEqual(
            self.window.status_bar.currentMessage(), tr("status.saved_to", path=self.item_named("a.txt").saved_path)
        )


class BatchStartedSignalTests(WindowTestCase):
    def test_once_for_each_time_work_starts_from_idle(self):
        started = []
        self.window.conversion_queue.batch_started.connect(lambda: started.append(1))

        self.add_sources("a.txt")
        self.add_sources("b.txt")
        self.assertEqual(len(started), 1)

        self.converter.release_all()
        settle()
        self.converter.hold_all()
        self.add_sources("c.txt")
        self.assertEqual(len(started), 2)


class HeldKeyTests(WindowTestCase):
    """`QTableView.selectRow` obeys held keys: with Shift it selects from an anchor that
    is not set, so nothing. A drop, or a file dialog's Open, may well come with one held."""

    def hold(self, key, modifier) -> None:
        self.window.show()
        process_events()
        handle = self.window.windowHandle()
        QTest.keyPress(handle, key, modifier)
        self.addCleanup(process_events)
        self.addCleanup(QTest.keyRelease, handle, key)
        process_events()
        self.assertEqual(QGuiApplication.keyboardModifiers(), modifier)

    def assert_row_stays_selected_through_a_conversion(self, adding) -> None:
        adding()
        self.assertEqual(self.window._selected_row(), 0)
        self.converter.release_all()
        settle()
        self.assertEqual(self.window._selected_row(), 0)
        self.assertTrue(self.window.preview_body.isVisibleTo(self.window.preview_panel))

    def test_a_file_added_with_shift_held(self):
        self.hold(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
        self.assert_row_stays_selected_through_a_conversion(lambda: self.add_sources("a.txt"))

    def test_a_link_added_with_shift_held(self):
        self.hold(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)

        def add_link():
            self.window.url_edit.setText("https://example.com")
            self.window.action_add_url()

        self.assert_row_stays_selected_through_a_conversion(add_link)

    def test_a_file_added_with_ctrl_held(self):
        self.hold(Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
        self.assert_row_stays_selected_through_a_conversion(lambda: self.add_sources("a.txt"))

    def test_a_row_finishing_with_shift_held_gets_selected(self):
        self.add_sources("a.txt")
        self.window.table_view.clearSelection()
        self.hold(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
        self.converter.release_all()
        settle()
        self.assertEqual(self.window._selected_row(), 0)

    def test_removing_with_shift_held_selects_the_next_row(self):
        self.add_sources("a.txt", "b.txt")
        self.window.table_view.selectRow(0)
        self.hold(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
        self.window.action_remove_selected()
        self.assertEqual(self.window._selected_row(), 0)
        self.assertEqual(self.window.model.item_at(0).display_name, "b.txt")
