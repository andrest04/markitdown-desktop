"""Counting a large saved text is costly, so it happens once and only for its own row."""
from __future__ import annotations

from unittest import mock

from qt_support import WindowTestCase, pump_until, settle

from app.core.queue_model import DisplayState, QueueItem, SourceKind
from app.i18n import LANG_ES
from app.i18n import manager as i18n_manager
from app.ui import queue_text


class WordCountCallsTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.item = self.item_named("a.txt")
        self.assertTrue(pump_until(lambda: self.item.display_state == DisplayState.SAVED))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        patcher = mock.patch.object(queue_text, "word_count", wraps=queue_text.word_count)
        self.count = patcher.start()
        self.addCleanup(patcher.stop)

    def header(self) -> str:
        return self.window.preview_header_status.text()

    def test_another_rows_start_and_finish_count_nothing(self):
        self.add_sources("b.txt")
        self.wait_started(2)
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").status.name == "CONVERTING"))
        self.converter.release("b.txt")
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").display_state == DisplayState.SAVED))
        settle()
        self.count.assert_not_called()

    def test_another_rows_failure_counts_nothing(self):
        self.converter.failures["b.txt"] = "boom"
        self.add_sources("b.txt")
        self.converter.release("b.txt")
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").error_message == "boom"))
        settle()
        self.count.assert_not_called()

    def test_typing_pauses_reuse_the_count(self):
        for text in ("one", "one two", "one two three"):
            self.window.raw_view.setPlainText(text)
            self.assertTrue(pump_until(lambda: not self.window._render_timer.isActive()))
        self.count.assert_not_called()
        self.assertTrue(self.header().endswith("2 words"), self.header())

    def test_coming_back_to_the_row_reuses_it(self):
        self.window.table_view.clearSelection()
        self.window.table_view.selectRow(0)
        self.window.table_view.clearSelection()
        self.window.table_view.selectRow(0)
        self.count.assert_not_called()

    def test_a_language_switch_reuses_it(self):
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertTrue(self.header().endswith("2 palabras"), self.header())
        self.count.assert_not_called()

    def test_saving_again_counts_the_new_text_once(self):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("no")):
            self.converter.release("a.txt")
            self.window.conversion_queue.enqueue([self.item], self.window.conversion_options)
            self.assertTrue(pump_until(lambda: self.item.display_state == DisplayState.SAVE_FAILED))
        settle()
        self.window.raw_view.setPlainText("one two three")
        self.assertTrue(pump_until(lambda: not self.window._render_timer.isActive()))
        self.count.reset_mock()

        self.window._start_conversion([0])
        self.window._refresh_preview()
        self.window._refresh_preview()

        self.assertEqual(self.count.call_count, 1)
        self.assertTrue(self.header().endswith("3 words"), self.header())

    def test_converting_again_counts_the_new_file(self):
        self.window.raw_view.setPlainText("one two three")
        self.converter.release("a.txt")
        self.window.conversion_queue.enqueue([self.item], self.window.conversion_options)
        self.assertTrue(pump_until(lambda: (self.downloads / "a (1).md").exists()))
        settle()
        self.assertEqual(self.count.call_count, 1)
        self.assertTrue(self.header().endswith("2 words"), self.header())


class HeaderOnUnrelatedRowsTests(WindowTestCase):
    def test_retry_still_appears_when_another_selected_row_fails(self):
        self.add_sources("a.txt", "b.txt")
        self.converter.release("a.txt")
        self.converter.failures["b.txt"] = "boom"
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVED))
        self.window.table_view.selectAll()
        self.assertEqual(self.window._selected_row(), 0)
        self.assertTrue(self.window.retry_header_btn.isHidden())

        self.converter.release("b.txt")
        self.assertTrue(pump_until(lambda: self.item_named("b.txt").error_message == "boom"))
        settle()

        self.assertFalse(self.window.retry_header_btn.isHidden())


class DetailStatusCountTests(WindowTestCase):
    def test_a_finished_item_not_saved_yet_still_counts_what_it_holds(self):
        item = QueueItem(source="/x/a.txt", kind=SourceKind.FILE, display_name="a.txt", markdown_result="one two")
        item.mark_converted("one two three")
        self.assertTrue(queue_text.detail_status(item).endswith("3 words"))
