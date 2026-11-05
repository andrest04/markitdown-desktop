"""The header's count describes the saved text, and edits never reach that file."""
from __future__ import annotations

from unittest import mock

from qt_support import WindowTestCase, pump_until

from app.core.queue_model import DisplayState, ItemStatus
from app.i18n import LANG_ES
from app.i18n import manager as i18n_manager

SAVED_COUNT = "2 words"  # "# converted a.txt"


class SavedWordCountTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.item = self.item_named("a.txt")
        self.assertTrue(pump_until(lambda: self.item.display_state == DisplayState.SAVED))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()

    def header(self) -> str:
        return self.window.preview_header_status.text()

    def edit(self, text: str) -> None:
        self.window.raw_view.setPlainText(text)
        self.assertTrue(pump_until(lambda: not self.window._render_timer.isActive()))

    def test_converted_text_is_counted(self):
        self.assertTrue(self.header().endswith(SAVED_COUNT), self.header())

    def test_edits_leave_the_count_alone_while_the_file_stays_as_it_was(self):
        self.edit("one two three four five six seven")
        self.assertEqual(self.item.markdown_result, "one two three four five six seven")
        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), "# converted a.txt")
        self.assertTrue(self.header().endswith(SAVED_COUNT), self.header())

    def test_clearing_the_tab_leaves_the_count_alone(self):
        self.edit("")
        self.window._update_preview_header(self.item)
        self.assertTrue(self.header().endswith(SAVED_COUNT), self.header())

    def test_coming_back_to_the_row_keeps_it(self):
        self.edit("one two three")
        self.window.table_view.clearSelection()
        self.window.table_view.selectRow(0)
        self.assertTrue(self.header().endswith(SAVED_COUNT), self.header())

    def test_a_language_switch_keeps_it(self):
        self.edit("one two three")
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertTrue(self.header().endswith("2 palabras"), self.header())

    def test_converting_again_counts_the_new_file(self):
        self.edit("one two three")
        self.converter.release("a.txt")
        self.window.conversion_queue.enqueue([self.item], self.window.conversion_options)
        self.assertTrue(pump_until(lambda: (self.downloads / "a (1).md").exists()))
        self.assertTrue(pump_until(lambda: self.item.status == ItemStatus.DONE and not self.window.conversion_queue.unfinished_count()))
        self.assertEqual(self.item.saved_text, "# converted a.txt")
        self.assertTrue(self.header().endswith(SAVED_COUNT), self.header())

    def test_a_save_after_edits_counts_the_edits_since_they_are_what_was_written(self):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("no")):
            self.window.conversion_queue.retry([self.item], self.window.conversion_options)
            self.converter.release("a.txt")
            self.window.conversion_queue.enqueue([self.item], self.window.conversion_options)
            self.assertTrue(pump_until(lambda: self.item.display_state == DisplayState.SAVE_FAILED))
        self.assertIsNone(self.item.saved_text)
        self.window.table_view.clearSelection()
        self.window.table_view.selectRow(0)

        self.edit("one two three")
        self.window._start_conversion([0])

        self.assertEqual(self.item.display_state, DisplayState.SAVED)
        self.assertEqual((self.downloads / "a (1).md").read_text(encoding="utf-8").strip(), "one two three")
        self.assertTrue(self.header().endswith("3 words"), self.header())
