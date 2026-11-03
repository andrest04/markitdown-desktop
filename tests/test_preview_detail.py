"""The detail pane says what is real about the output, and the preview reads well."""
from __future__ import annotations

import unittest

from qt_support import WindowTestCase, process_events

from app.core.queue_model import ItemStatus, QueueItem, SourceKind
from app.i18n import LANG_EN, LANG_ES, tr
from app.i18n import manager as i18n_manager


def make_item(status=ItemStatus.DONE, saved="", save_error="", error="", result=None):
    return QueueItem(
        source="/somewhere/report.pdf",
        kind=SourceKind.FILE,
        display_name="report.pdf",
        status=status,
        saved_path=saved,
        save_error=save_error,
        error_message=error,
        markdown_result=result,
    )


class WordCountTests(unittest.TestCase):
    def count(self, text):
        from app.ui.queue_delegate import word_count

        return word_count(text)

    def test_counts_words_and_not_markdown_syntax(self):
        self.assertEqual(self.count("# Title\n\n- one two\n- three\n\n> four"), 5)
        self.assertEqual(self.count("| a | b |\n| --- | --- |\n| c | d |"), 4)
        self.assertEqual(self.count("***\n\n---"), 0)

    def test_words_keep_their_inner_punctuation(self):
        self.assertEqual(self.count("self-hosted v1.2, don't [link](http://x.y)"), 4)

    def test_accented_words_count(self):
        self.assertEqual(self.count("añadió él ñu"), 3)

    def test_nothing_is_zero(self):
        self.assertEqual(self.count(""), 0)
        self.assertEqual(self.count(None), 0)


class DetailLineTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, i18n_manager, "_language", LANG_EN)
        i18n_manager._language = LANG_EN

    def line(self, item):
        from app.ui.queue_delegate import detail_status

        return detail_status(item)

    def test_saved_names_the_real_file_and_its_size(self):
        item = make_item(saved="/home/me/Downloads/report (1).md", result="one two three")
        self.assertEqual(self.line(item), "Saved as report (1).md in Downloads, 3 words")

    def test_one_word_and_zero_words_read_honestly(self):
        self.assertTrue(self.line(make_item(saved="/x/a.md", result="one")).endswith(", 1 word"))
        self.assertTrue(self.line(make_item(saved="/x/a.md", result="")).endswith(", 0 words"))

    def test_converted_but_not_yet_saved_gives_the_size(self):
        self.assertEqual(self.line(make_item(result="one two")), "Converted, 2 words")

    def test_large_counts_use_the_language_separator(self):
        text = "word " * 12480
        self.assertTrue(self.line(make_item(saved="/x/a.md", result=text)).endswith("12,480 words"))
        i18n_manager._language = LANG_ES
        self.assertEqual(
            self.line(make_item(saved="/x/a.md", result=text)),
            "Guardado como a.md en Descargas, 12.480 palabras",
        )

    def test_a_save_failure_leads_with_the_failure(self):
        self.assertEqual(
            self.line(make_item(save_error="[Errno 28] disk full", result="one")),
            tr("status.save_failed_detail", error="disk full"),
        )

    def test_a_failed_item_gives_the_reason_or_falls_back(self):
        self.assertEqual(self.line(make_item(ItemStatus.ERROR, error="boom")), "boom")
        self.assertEqual(self.line(make_item(ItemStatus.ERROR)), tr("preview.failed"))

    def test_nothing_else_claims_a_size(self):
        self.assertEqual(self.line(make_item(ItemStatus.PENDING)), tr("preview.pending"))
        self.assertEqual(self.line(make_item(ItemStatus.CONVERTING)), tr("preview.converting"))


class PreviewHtmlTests(unittest.TestCase):
    def html(self, source):
        import markdown

        from app.ui.theme import preview_html

        return preview_html(markdown.markdown(source, extensions=["extra", "sane_lists", "tables"]), "light")

    def test_a_code_block_gets_even_padding_and_no_blank_last_line(self):
        html = self.html("```\nfirst\nsecond\n```")
        self.assertIn('cellpadding="12"', html)
        self.assertIn("second</code></pre>", html)

    def test_a_blockquote_is_drawn_apart_from_the_text(self):
        html = self.html("> Quoted words")
        self.assertNotIn("<blockquote>", html)
        self.assertIn("Quoted words", html)
        self.assertIn('width="1"', html)

    def test_tables_and_lists_keep_their_distance_from_neighbors(self):
        html = self.html("| a |\n| --- |\n| b |")
        self.assertIn("margin-top", html)
        self.assertIn("margin-bottom", html)

    def test_escaped_markup_in_code_stays_escaped(self):
        html = self.html("```\n<pre>not real</pre>\n```")
        self.assertIn("&lt;pre&gt;not real&lt;/pre&gt;", html)

    def test_plain_text_passes_through(self):
        self.assertIn("<p>hello</p>", self.html("hello"))

    def test_wide_tables_escape_the_reading_measure_and_prose_does_not(self):
        from app.ui.theme import needs_full_width

        self.assertFalse(needs_full_width(self.html("plain text")))
        self.assertFalse(needs_full_width(self.html("| a | b |\n| --- | --- |\n| c | d |")))
        wide = "| a | b | c | d | e |\n| --- | --- | --- | --- | --- |\n| 1 | 2 | 3 | 4 | 5 |"
        self.assertTrue(needs_full_width(self.html(wide)))


class WindowDetailTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1280, 800)
        self.window.show()
        process_events()

    def select(self, item):
        self.window.model.add_item(item)
        self.window._update_drop_zone_prominence()
        self.window.table_view.selectRow(self.window.model.rowCount() - 1)
        process_events()

    def test_the_header_shows_the_saved_name_and_size(self):
        self.select(make_item(saved="/x/report.md", result="one two"))
        self.assertEqual(self.window.preview_header_status.text(), "Saved as report.md in Downloads, 2 words")

    def test_the_header_retranslates_live(self):
        self.select(make_item(saved="/x/report.md", result="one two"))
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertEqual(self.window.preview_header_status.text(), "Guardado como report.md en Descargas, 2 palabras")

    def test_editing_the_markdown_updates_the_size(self):
        self.select(make_item(saved="/x/report.md", result="one two"))
        self.window.raw_view.setPlainText("one two three")
        process_events()
        self.assertTrue(self.window.preview_header_status.text().endswith("3 words"))

    def test_selecting_an_item_does_not_write_back_through_the_guard(self):
        item = make_item(saved="/x/report.md", result="one two")
        self.select(item)
        self.assertEqual(item.markdown_result, "one two")

    def test_a_failure_shows_the_whole_message_when_there_is_more_to_it(self):
        message = "File conversion failed after 1 attempts:\n - PdfConverter threw E with message: No /Root object\n"
        self.select(make_item(ItemStatus.ERROR, error=message))
        self.assertEqual(self.window.preview_header_status.text(), "No /Root object")
        self.assertTrue(self.window.preview_error_detail.isVisible())
        self.assertIn("PdfConverter", self.window.preview_error_detail.text())

    def test_a_short_failure_does_not_repeat_itself(self):
        self.select(make_item(ItemStatus.ERROR, error="boom"))
        self.assertFalse(self.window.preview_error_detail.isVisible())

    def test_other_states_hide_the_message(self):
        self.select(make_item(ItemStatus.ERROR, error="a\nb"))
        self.assertTrue(self.window.preview_error_detail.isVisible())
        self.select(make_item(saved="/x/report.md", result="one"))
        self.assertFalse(self.window.preview_error_detail.isVisible())

    def test_a_wide_table_gets_the_pane_and_prose_keeps_the_measure(self):
        from app.ui.theme import READING_WIDTH

        view = self.window.rendered_view
        self.select(make_item(saved="/x/a.md", result="words"))
        self.assertEqual(view.lineWrapColumnOrWidth(), READING_WIDTH)
        wide = "| a | b | c | d | e |\n| --- | --- | --- | --- | --- |\n| 1 | 2 | 3 | 4 | 5 |"
        self.select(make_item(saved="/x/b.md", result=wide))
        self.assertEqual(view.lineWrapColumnOrWidth(), view.viewport().width())


if __name__ == "__main__":
    unittest.main()
