"""The close question follows the queue while it is open.

These run the real `exec`, whose nested event loop is what delivers worker results
while the question is on screen. Steps are chained on the queue's own signals, never
on elapsed time. A watchdog clicks Keep converting so a failing test fails instead of
hanging, and it is stopped before the test ends, so it cannot reach a later dialog.
"""
from __future__ import annotations

from unittest import mock

from PySide6.QtCore import SIGNAL, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from qt_support import FakeSettings, WindowTestCase, pump_until, settle

from app.core.queue_model import DisplayState, ItemStatus
from app.i18n import tr

WATCHDOG_MS = 20_000
PROGRESS = SIGNAL("progress_changed(int,int)")


class CloseDialogTestCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.settings = FakeSettings()
        self.window.show()
        self.texts: list[str] = []
        self.watchdog = QTimer()
        self.watchdog.setSingleShot(True)
        self.watchdog.setInterval(WATCHDOG_MS)
        self.watchdog.timeout.connect(lambda: self.click("msgbox.close_busy.keep"))
        self.addCleanup(self.watchdog.stop)

    def open_box(self) -> QMessageBox | None:
        box = QApplication.activeModalWidget()
        return box if isinstance(box, QMessageBox) else None

    def click(self, key: str) -> None:
        box = self.open_box()
        if box is not None:
            next(button for button in box.buttons() if button.text() == tr(key)).click()

    def note_text(self) -> None:
        box = self.open_box()
        self.texts.append(box.text() if box is not None else "")

    def close_while(self, on_open) -> bool:
        """Close, and run `on_open` once the box's event loop is running."""
        QTimer.singleShot(0, on_open)
        self.watchdog.start()
        closed = self.window.close()
        self.watchdog.stop()
        return closed

    def after_each_result(self, *steps) -> None:
        """Run one step after each result. The box's own slot, connected earlier, runs first."""
        remaining = list(steps)

        def next_step(*_args):
            if remaining:
                remaining.pop(0)()

        self.window.conversion_queue.progress_changed.connect(next_step)
        self.addCleanup(self.window.conversion_queue.progress_changed.disconnect, next_step)

    def assert_box_gone_and_window_open(self, closed: bool) -> None:
        self.assertFalse(closed)
        self.assertIsNone(self.open_box())
        self.assertTrue(self.window.isVisible())


class ClosesWhenAllSavedTests(CloseDialogTestCase):
    def test_it_closes_when_the_last_conversion_is_saved(self):
        self.add_sources("a.txt")
        self.wait_started(1)

        closed = self.close_while(lambda: self.converter.release("a.txt"))

        self.assertTrue(closed)
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.open_box())
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertIn("window/geometry", self.window.settings.values)

    def test_the_count_follows_and_it_closes_after_the_last(self):
        self.add_sources("a.txt", "b.txt", "c.txt")
        self.wait_started(3)

        def start():
            self.note_text()
            self.after_each_result(
                lambda: (self.note_text(), self.converter.release("b.txt")),
                lambda: (self.note_text(), self.converter.release("c.txt")),
            )
            self.converter.release("a.txt")

        closed = self.close_while(start)

        self.assertEqual(
            self.texts,
            [
                tr("msgbox.close_busy.text.other", count=3),
                tr("msgbox.close_busy.text.other", count=2),
                tr("msgbox.close_busy.text.one"),
            ],
        )
        self.assertTrue(closed)
        self.assertEqual(self.downloaded_names(), ["a.md", "b.md", "c.md"])

    def test_an_earlier_failure_it_was_not_waiting_on_does_not_keep_it_open(self):
        self.converter.failures["old.txt"] = "boom"
        self.add_sources("old.txt")
        self.converter.release("old.txt")
        self.assertTrue(pump_until(lambda: self.item_named("old.txt").status == ItemStatus.ERROR))
        settle()
        self.add_sources("a.txt")
        self.wait_started(2)

        self.assertTrue(self.close_while(lambda: self.converter.release("a.txt")))


class StaysOpenOnFailureTests(CloseDialogTestCase):
    def test_a_failed_save_keeps_the_window_and_the_text(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        item = self.item_named("a.txt")

        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("no room")):
            closed = self.close_while(lambda: self.converter.release("a.txt"))

        self.assert_box_gone_and_window_open(closed)
        self.assertEqual(item.display_state, DisplayState.SAVE_FAILED)
        self.assertEqual(item.markdown_result, "# converted a.txt")
        self.assertEqual(self.window._selected_row(), 0)
        self.assertFalse(self.window.retry_header_btn.isHidden())

    def test_a_failed_conversion_keeps_the_window(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.wait_started(1)

        closed = self.close_while(lambda: self.converter.release("a.txt"))

        self.assert_box_gone_and_window_open(closed)
        self.assertEqual(self.item_named("a.txt").status, ItemStatus.ERROR)

    def test_one_failure_among_saved_ones_keeps_the_window_and_shows_that_row(self):
        self.converter.failures["b.txt"] = "boom"
        self.add_sources("a.txt", "b.txt", "c.txt")
        self.wait_started(3)
        self.window.table_view.selectRow(0)

        def start():
            self.after_each_result(
                lambda: self.converter.release("b.txt"),
                lambda: self.converter.release("c.txt"),
            )
            self.converter.release("a.txt")

        closed = self.close_while(start)

        self.assert_box_gone_and_window_open(closed)
        self.assertEqual(self.window._selected_row(), 1)
        self.assertEqual(self.downloaded_names(), ["a.md", "c.md"])

    def test_closing_again_afterwards_asks_nothing_and_closes(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.wait_started(1)
        self.assertFalse(self.close_while(lambda: self.converter.release("a.txt")))
        settle()
        self.assertTrue(self.window.close())


class ButtonsTests(CloseDialogTestCase):
    def test_keep_after_a_partial_change_keeps_the_window(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)

        def start():
            self.after_each_result(lambda: self.click("msgbox.close_busy.keep"))
            self.converter.release("a.txt")

        self.assertFalse(self.close_while(start))

        self.assertTrue(self.window.isVisible())
        self.converter.release("b.txt")
        settle()
        self.assertEqual(self.downloaded_names(), ["a.md", "b.md"])
        self.assertTrue(self.window.isVisible())

    def test_keep_is_not_overruled_by_a_batch_finishing_later(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        self.assertFalse(self.close_while(lambda: self.click("msgbox.close_busy.keep")))

        self.converter.release("a.txt")
        settle()

        self.assertTrue(self.window.isVisible())

    def test_a_button_clicked_as_the_last_result_arrives_is_respected(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        item = self.item_named("a.txt")
        queue = self.window.conversion_queue

        def click_then_finish():
            # In one go, so the result lands before `exec` has returned from the click.
            self.click("msgbox.close_busy.keep")
            queue._on_finished(item, "# text")

        self.assertFalse(self.close_while(click_then_finish))
        self.assertTrue(self.window.isVisible())

    def test_close_anyway_still_closes_with_work_left(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)

        self.assertTrue(self.close_while(lambda: self.click("msgbox.close_busy.close")))

        self.assertEqual(self.downloaded_names(), [])

    def test_the_box_stops_listening_when_it_ends(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        queue = self.window.conversion_queue
        before = queue.receivers(PROGRESS)
        during: list[int] = []

        def look_then_keep():
            during.append(queue.receivers(PROGRESS))
            self.click("msgbox.close_busy.keep")

        self.close_while(look_then_keep)

        self.assertEqual(during, [before + 1])
        self.assertEqual(queue.receivers(PROGRESS), before)
