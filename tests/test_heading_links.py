"""A link to a plain heading scrolls there, without a table of contents appearing."""
from __future__ import annotations

import unittest

import markdown
import test_preview_links
from qt_support import process_events

from app.ui.theme import HeadingIds, heading_anchor

FILLER = "\n\n".join(f"Paragraph {number}" for number in range(120))


def html_of(source: str) -> str:
    return markdown.markdown(source, extensions=["extra", HeadingIds()])


class HeadingAnchorTests(test_preview_links.PreviewTestCase):
    click_link = test_preview_links.LinkTests.click_link

    def scrolled_by_clicking(self, heading: str, href: str) -> int:
        self.show_markdown(f"[go]({href})\n\n{FILLER}\n\n{heading}\n\nBody\n\n{FILLER}")
        return self.click_and_measure(href)

    def click_and_measure(self, href: str) -> int:
        scrollbar = self.view.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        self.click_link(href)
        process_events()
        return scrollbar.value()

    def test_a_link_scrolls_to_a_plain_heading(self):
        self.assertGreater(self.scrolled_by_clicking("# Section", "#section"), 0)

    def test_a_heading_of_several_words(self):
        self.assertGreater(self.scrolled_by_clicking("## Next Steps", "#next-steps"), 0)

    def test_an_accented_heading_keeps_its_letters(self):
        self.assertGreater(self.scrolled_by_clicking("## Sección Uno", "#sección-uno"), 0)

    def test_punctuation_goes_the_way_github_names_it(self):
        self.assertGreater(self.scrolled_by_clicking("## Credits & License", "#credits--license"), 0)

    def test_a_link_to_nothing_does_not_scroll(self):
        self.assertEqual(self.scrolled_by_clicking("# Section", "#elsewhere"), 0)

    def test_a_link_differing_only_in_case_scrolls(self):
        # A real HTML conversion gave `#History` for a heading whose id is `history`.
        self.assertGreater(self.scrolled_by_clicking("## History", "#History"), 0)

    def test_the_second_heading_of_a_name_is_reachable(self):
        self.show_markdown(
            f"[one](#notes) [two](#notes-1)\n\n{FILLER}\n\n## Notes\n\nBody\n\n{FILLER}\n\n## Notes\n\nBody\n\n{FILLER}"
        )
        first = self.click_and_measure("#notes")
        second = self.click_and_measure("#notes-1")
        self.assertGreater(first, 0)
        self.assertGreater(second, first)

    def test_an_exact_match_beats_one_differing_in_case(self):
        filler = "<p>x</p>" * 120
        self.view.setHtml(f"{filler}<h2 id='foo'>a</h2>{filler}<h2 id='Foo'>b</h2>{filler}")
        process_events()
        scrollbar = self.view.verticalScrollBar()
        self.view._on_link_clicked(self.url("#foo"))
        lower = scrollbar.value()
        scrollbar.setValue(0)
        self.view._on_link_clicked(self.url("#Foo"))
        self.assertGreater(scrollbar.value(), lower)

    @staticmethod
    def url(href: str):
        from PySide6.QtCore import QUrl

        return QUrl(href)

    def test_the_marker_is_left_as_text_with_no_contents_list(self):
        self.show_markdown("[TOC]\n\n# One\n\n## Two")
        text = self.view.toPlainText()
        self.assertIn("[TOC]", text)
        self.assertEqual(text.count("One"), 1)
        self.assertEqual(text.count("Two"), 1)

    def test_a_heading_with_no_marker_adds_nothing_visible(self):
        self.show_markdown("# One")
        self.assertEqual(self.view.toPlainText().strip(), "One")


class HeadingIdTests(unittest.TestCase):
    def test_names(self):
        for heading, name in (
            ("Section", "section"),
            ("Next Steps", "next-steps"),
            ("Credits & License", "credits--license"),
            ("Sección Uno", "sección-uno"),
            ("v1.2 Notes", "v12-notes"),
            ("snake_case and-dash", "snake_case-and-dash"),
        ):
            with self.subTest(heading=heading):
                self.assertEqual(heading_anchor(heading), name)

    def test_duplicates_number_the_way_github_does(self):
        html = html_of("## Notes\n\n## Notes\n\n## Notes")
        self.assertEqual(html.count('id="notes"'), 1)
        self.assertEqual(html.count('id="notes-1"'), 1)
        self.assertEqual(html.count('id="notes-2"'), 1)

    def test_a_duplicate_does_not_take_a_name_already_in_use(self):
        html = html_of("## Notes 1\n\n## Notes\n\n## Notes")
        self.assertIn('id="notes-1"', html)
        self.assertIn('id="notes"', html)
        self.assertIn('id="notes-2"', html)

    def test_an_id_set_in_the_text_is_kept_and_not_handed_out_again(self):
        html = html_of("## Other {#notes}\n\n## Notes")
        self.assertIn('<h2 id="notes">Other</h2>', html)
        self.assertIn('<h2 id="notes-1">Notes</h2>', html)

    def test_inline_markup_counts_by_its_text(self):
        self.assertIn('id="use-foo-now"', html_of("## Use `foo` *now*"))
        self.assertIn('id="read-this"', html_of("## [Read](http://x.y) this"))

    def test_a_heading_with_no_name_gets_no_id(self):
        html = html_of("# !!!")
        self.assertNotIn("id=", html)
        self.assertIn("!!!", html)

    def test_every_level_is_covered(self):
        html = html_of("\n\n".join(f"{'#' * level} H{level}" for level in range(1, 7)))
        for level in range(1, 7):
            self.assertIn(f'id="h{level}"', html)

    def test_the_marker_stays_text(self):
        self.assertIn("[TOC]", html_of("# One\n\n[TOC]"))
