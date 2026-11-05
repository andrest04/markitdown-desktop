"""A very long result must not freeze the window, and nothing may seem lost to it."""
from __future__ import annotations

from unittest import mock

from qt_support import WindowTestCase, process_events, pump_until

from app.core.queue_model import ItemStatus, QueueItem, SourceKind
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui import main_window
from app.ui.main_window import PREVIEW_CHAR_LIMIT, preview_excerpt

ROW = "| row | 12345 |\n"
HEADER = "| Name | Value |\n| --- | --- |\n"


def long_table() -> str:
    return HEADER + ROW * (PREVIEW_CHAR_LIMIT // len(ROW) * 3)


def make_item(text: str, saved: str = "/x/report.md", save_error: str = "") -> QueueItem:
    return QueueItem(
        source="/somewhere/report.pdf",
        kind=SourceKind.FILE,
        display_name="report.pdf",
        status=ItemStatus.DONE,
        markdown_result=text,
        saved_path=saved,
        save_error=save_error,
    )


class ExcerptTests(WindowTestCase):
    def test_short_text_is_left_alone(self):
        self.assertEqual(preview_excerpt("# one\n\ntwo"), "# one\n\ntwo")

    def test_text_exactly_at_the_limit_is_left_alone(self):
        text = "x" * PREVIEW_CHAR_LIMIT
        self.assertIs(preview_excerpt(text), text)

    def test_long_text_is_cut_at_a_line_boundary(self):
        text = long_table()
        excerpt = preview_excerpt(text)
        self.assertLessEqual(len(excerpt), PREVIEW_CHAR_LIMIT)
        self.assertTrue(excerpt.endswith(ROW))
        self.assertTrue(text.startswith(excerpt))

    def test_a_single_endless_line_is_still_cut(self):
        # A long data URI or minified page has no line boundary to find.
        excerpt = preview_excerpt("x" * (PREVIEW_CHAR_LIMIT * 2))
        self.assertEqual(len(excerpt), PREVIEW_CHAR_LIMIT)


class PreviewCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        process_events()

    def select(self, item: QueueItem) -> QueueItem:
        self.window.model.add_item(item)
        self.window._update_drop_zone_prominence()
        self.window.table_view.selectRow(self.window.model.rowCount() - 1)
        process_events()
        return item

    def preview_text(self) -> str:
        return self.window.rendered_view.toPlainText()


class LargeResultTests(PreviewCase):
    def test_the_preview_renders_only_the_beginning_and_says_so(self):
        text = long_table()
        with mock.patch.object(main_window.markdown_lib, "markdown", wraps=main_window.markdown_lib.markdown) as render:
            self.select(make_item(text))
        rendered = render.call_args.args[0]
        self.assertLessEqual(len(rendered), PREVIEW_CHAR_LIMIT)
        self.assertTrue(rendered.endswith(ROW))
        self.assertIn(tr("preview.truncated"), self.preview_text())

    def test_the_markdown_tab_and_the_item_stay_complete(self):
        text = long_table()
        item = self.select(make_item(text))
        self.assertEqual(self.window.raw_view.toPlainText(), text.rstrip("\n") + "\n")
        self.assertEqual(item.markdown_result, text)

    def test_a_short_result_has_no_notice(self):
        self.select(make_item("# short"))
        self.assertNotIn(tr("preview.truncated"), self.preview_text())
        self.assertNotIn(tr("preview.truncated_unsaved"), self.preview_text())

    def test_the_notice_does_not_promise_a_file_that_was_not_saved(self):
        self.select(make_item(long_table(), saved="", save_error="disk full"))
        self.assertIn(tr("preview.truncated_unsaved"), self.preview_text())
        self.assertNotIn(tr("preview.truncated"), self.preview_text())

    def test_the_notice_follows_a_language_switch(self):
        self.select(make_item(long_table()))
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertIn("La pestaña Markdown", self.preview_text())

    def test_a_theme_switch_keeps_the_cut_and_the_notice(self):
        self.select(make_item(long_table()))
        before = self.preview_text()
        self.window._set_theme_preference("dark")
        self.assertEqual(self.preview_text(), before)
        self.window._set_theme_preference("light")
        self.assertEqual(self.preview_text(), before)


class TypingDebounceTests(PreviewCase):
    def test_typing_renders_once_after_the_last_edit(self):
        item = self.select(make_item("start"))
        with mock.patch.object(self.window, "_render_markdown", wraps=self.window._render_markdown) as render:
            for text in ("one", "one two", "one two three"):
                self.window.raw_view.setPlainText(text)
            render.assert_not_called()
            self.assertEqual(item.markdown_result, "one two three")
            self.assertTrue(pump_until(lambda: render.call_count > 0))
        render.assert_called_once_with("one two three")
        self.assertEqual(self.preview_text(), "one two three")

    def test_changing_rows_during_the_wait_loses_no_edit(self):
        first = self.select(make_item("first"))
        second = self.select(make_item("second", saved="/x/other.md"))
        self.window.table_view.selectRow(0)
        process_events()

        self.window.raw_view.setPlainText("first edited")
        self.window.table_view.selectRow(1)
        process_events()

        self.assertEqual(first.markdown_result, "first edited")
        self.assertEqual(second.markdown_result, "second")
        self.assertEqual(self.preview_text(), "second")
        self.assertFalse(self.window._render_timer.isActive())

        self.window.table_view.selectRow(0)
        process_events()
        self.assertEqual(self.preview_text(), "first edited")
