"""Retry after a failed save writes the text in memory, without converting again."""
from __future__ import annotations

import errno
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThread
from PySide6.QtGui import QGuiApplication
from qt_support import WindowTestCase, pump_until, settle

from app.core.queue_model import DisplayState, ItemStatus
from app.i18n import tr

NO_ROOM = OSError(errno.ENOSPC, "No space left on device")


class RetrySaveTestCase(WindowTestCase):
    def failed_save(self, name: str = "a.txt"):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=NO_ROOM):
            self.add_sources(name)
            self.converter.release(name)
            self.assertTrue(pump_until(lambda: self.item_named(name).display_state == DisplayState.SAVE_FAILED))
        return self.item_named(name)

    def spy(self, signal) -> list:
        seen: list = []
        signal.connect(lambda *args: seen.append(args))
        return seen


class RetrySavesTests(RetrySaveTestCase):
    def test_retry_saves_the_text_without_converting_after_the_source_went_away(self):
        item = self.failed_save()
        Path(item.source).unlink()

        self.window._start_conversion([0])
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(item.display_state, DisplayState.SAVED)
        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), "# converted a.txt")
        self.assertEqual(item.save_error, "")

    def test_every_way_to_retry_saves(self):
        for name, retry in (
            ("action", lambda: self.window.action_convert_selected()),
            ("row", lambda: self.window.queue_delegate.retry_requested.emit(0)),
            ("enter", lambda: self.window._retry_focused_row()),
        ):
            with self.subTest(way=name):
                self.window.action_clear_all()
                item = self.failed_save(f"{name}.txt")
                self.window.table_view.selectRow(0)
                self.window.table_view.setCurrentIndex(self.window.model.index(0, 0))
                retry()
                settle()
                self.assertEqual(item.display_state, DisplayState.SAVED)
                self.assertEqual(self.converter.call_count(f"{name}.txt"), 1)

    def test_it_saves_on_the_gui_thread(self):
        self.failed_save()
        threads = []

        def recording_save(item, text, directory=None):
            threads.append(QThread.currentThread())
            return self.downloads / "a.md"

        with mock.patch("app.core.conversion_queue.auto_save_markdown", recording_save):
            self.window._start_conversion([0])
        self.assertEqual(threads, [self.window.thread()])

    def test_a_save_that_fails_again_says_so_and_keeps_the_text(self):
        item = self.failed_save()
        failed = self.spy(self.window.conversion_queue.item_save_failed)

        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=NO_ROOM):
            self.window._start_conversion([0])

        self.assertEqual(failed, [(item, str(NO_ROOM))])
        self.assertEqual(item.display_state, DisplayState.SAVE_FAILED)
        self.assertEqual(item.markdown_result, "# converted a.txt")
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_it_saves_what_the_markdown_tab_holds_now(self):
        self.failed_save()
        self.window.table_view.selectRow(0)
        self.window.raw_view.setPlainText("# edited before saving")

        self.window._start_conversion([0])

        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), "# edited before saving")

    def test_text_edited_away_converts_again_and_never_writes_an_empty_file(self):
        for blank in ("", "  \n"):
            with self.subTest(blank=blank):
                self.window.action_clear_all()
                self.converter.hold_all()
                item = self.failed_save("a.txt")
                item.markdown_result = blank
                before = self.converter.call_count("a.txt")

                self.converter.release_all()
                self.window._start_conversion([0])
                settle()

                self.assertEqual(self.converter.call_count("a.txt"), before + 1)
                self.assertEqual(item.markdown_result, "# converted a.txt")
                written = [(self.downloads / name).read_text(encoding="utf-8") for name in self.downloaded_names()]
                self.assertTrue(all(text.strip() for text in written), written)

    def test_an_item_already_dispatched_is_not_saved_on_top_of_its_conversion(self):
        item = self.failed_save()
        self.window.conversion_queue.enqueue([item], self.window.conversion_options)

        self.window._start_conversion([0])

        self.assertEqual(self.downloaded_names(), [])
        self.converter.release_all()
        settle()
        self.assertEqual(self.downloaded_names(), ["a.md"])


class RetrySaveSignalsTests(RetrySaveTestCase):
    def test_a_save_alone_touches_neither_progress_nor_the_batch(self):
        self.failed_save()
        settle()
        queue = self.window.conversion_queue
        progress = self.spy(queue.progress_changed)
        batches = self.spy(queue.batch_finished)

        self.window._start_conversion([0])

        self.assertEqual(progress, [])
        self.assertEqual(batches, [])

    def test_the_status_bar_reports_the_save(self):
        item = self.failed_save()
        self.window._start_conversion([0])
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.saved_to", path=item.saved_path))

    def test_the_row_and_header_update(self):
        item = self.failed_save()
        self.window.table_view.selectRow(0)
        self.assertFalse(self.window.retry_header_btn.isHidden())

        self.window._start_conversion([0])

        self.assertEqual(item.display_state, DisplayState.SAVED)
        self.assertTrue(self.window.retry_header_btn.isHidden())
        self.assertFalse(self.window.open_file_btn.isHidden())

    def test_totals_of_a_running_batch_are_left_alone(self):
        self.failed_save()
        self.add_sources("b.txt")
        self.wait_started(2)
        before = self.progress_state()
        batches = self.spy(self.window.conversion_queue.batch_finished)

        self.window._start_conversion([0])

        self.assertEqual(self.progress_state(), before)
        self.assertEqual(batches, [])
        self.converter.release_all()
        settle()
        self.assertEqual(self.progress_state()[:2], (1, 1))
        self.assertEqual(len(batches), 1)

    def test_a_mixed_retry_saves_one_and_converts_the_other(self):
        saved = self.failed_save()
        self.converter.failures["b.txt"] = "boom"
        self.add_sources("b.txt")
        self.converter.release("b.txt")
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").status == ItemStatus.ERROR))
        del self.converter.failures["b.txt"]
        self.window.table_view.selectAll()

        self.converter.release_all()
        self.window.action_convert_selected()
        settle()

        self.assertEqual(saved.display_state, DisplayState.SAVED)
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.converter.call_count("b.txt"), 2)
        self.assertEqual(self.downloaded_names(), ["a.md", "b.md"])


class HeldTextStaysReachableTests(RetrySaveTestCase):
    def failed_after_failed_save(self):
        """Never saved, then a conversion that failed: its text is the only copy."""
        item = self.failed_save()
        self.converter.failures["a.txt"] = "boom"
        self.window.conversion_queue.enqueue([item], self.window.conversion_options)
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR))
        return item

    def assert_text_reachable(self, item) -> None:
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        self.assertFalse(self.window.copy_btn.isHidden())
        self.assertTrue(self.window.copy_action.isEnabled())
        self.assertTrue(self.window.save_copy_action.isEnabled())

        self.window.raw_view.blockSignals(True)
        self.window.raw_view.setPlainText("something else on screen")
        self.window.raw_view.blockSignals(False)
        self.window.action_copy_raw()
        self.assertEqual(QGuiApplication.clipboard().text(), item.markdown_result)

        target = self.tmp / "copy.md"
        with mock.patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            self.window.action_save_current()
        self.assertEqual(target.read_text(encoding="utf-8"), item.markdown_result)

        folder = self.tmp / "out"
        folder.mkdir()
        with mock.patch("app.ui.main_window.QFileDialog.getExistingDirectory", return_value=str(folder)):
            self.window.action_export_all()
        self.assertEqual((folder / "a.md").read_text(encoding="utf-8"), item.markdown_result)

    def test_after_a_failed_save(self):
        self.assert_text_reachable(self.failed_save())

    def test_after_a_failed_conversion_of_text_that_never_reached_a_file(self):
        self.assert_text_reachable(self.failed_after_failed_save())

    def test_a_failed_retry_of_a_saved_item_still_offers_nothing(self):
        # See StaleResultTests: a file holds that text, and it is out of date.
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVED))
        self.converter.failures["a.txt"] = "boom"
        self.window._start_conversion([0])
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        self.assertTrue(self.window.copy_btn.isHidden())

    def test_retry_stays_the_primary_on_a_failure_that_holds_text(self):
        self.failed_after_failed_save()
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        self.assertEqual(self.window.retry_header_btn.property("tier"), "primary")
        self.assertEqual(self.window.copy_btn.property("tier"), "quiet")

    def test_a_first_failure_has_nothing_to_offer(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR))
        self.window._refresh_preview()
        self.assertTrue(self.window.copy_btn.isHidden())
        self.assertFalse(self.window.save_copy_action.isEnabled())

    def test_nothing_is_offered_while_it_converts_again(self):
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVED))
        self.window._start_conversion([0])
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.CONVERTING))
        self.window._refresh_preview()
        self.assertTrue(self.window.copy_btn.isHidden())
