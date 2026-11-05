"""A link to a plain heading scrolls there, without a table of contents appearing."""
from __future__ import annotations

import unittest

import test_preview_links
from qt_support import process_events

from app.ui.main_window import heading_anchor

FILLER = "\n\n".join(f"Paragraph {number}" for number in range(120))


class HeadingAnchorTests(test_preview_links.PreviewTestCase):
    click_link = test_preview_links.LinkTests.click_link

    def scrolled_by_clicking(self, heading: str, href: str) -> int:
        self.window.table_view.selectRow(0)
        self.show_markdown(f"[go]({href})\n\n{FILLER}\n\n{heading}\n\nBody\n\n{FILLER}")
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

    def test_the_marker_is_left_as_text_with_no_contents_list(self):
        self.show_markdown("[TOC]\n\n# One\n\n## Two")
        text = self.view.toPlainText()
        self.assertIn("[TOC]", text)
        self.assertEqual(text.count("One"), 1)
        self.assertEqual(text.count("Two"), 1)

    def test_a_heading_with_no_marker_adds_nothing_visible(self):
        self.show_markdown("# One")
        self.assertEqual(self.view.toPlainText().strip(), "One")


class HeadingNameTests(unittest.TestCase):
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
                self.assertEqual(heading_anchor(heading, "-"), name)
