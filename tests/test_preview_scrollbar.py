"""The preview's scrollbar stays thin and quiet on the sheet, and stays visible."""
from __future__ import annotations

import unittest

from PySide6.QtGui import QColor
from qt_support import WindowTestCase, process_events
from test_theme_contrast import contrast

from app.core.queue_model import ItemStatus, QueueItem, SourceKind
from app.ui.theme import tokens_for

_LONG_MARKDOWN = "\n\n".join(f"## Section {n}\n\nSome words to fill the sheet." for n in range(80))


class ScrollbarTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        self.window.model.add_item(
            QueueItem(
                source="/x/a.txt",
                kind=SourceKind.FILE,
                display_name="a.txt",
                status=ItemStatus.DONE,
                saved_path="/x/a.md",
                markdown_result=_LONG_MARKDOWN,
            )
        )
        self.window._update_drop_zone_prominence()
        self.window.table_view.selectRow(0)
        process_events()

    def _handle_columns(self, theme: str) -> int:
        self.window._set_theme_preference(theme)
        process_events()
        bar = self.window.rendered_view.verticalScrollBar()
        self.assertTrue(bar.isVisible(), "the preview must overflow for this test")
        image = bar.grab().toImage()
        edge = QColor(tokens_for(theme).edge)
        # The handle sits at the top; below its rounded end is a clean row of pixels.
        return sum(image.pixelColor(x, 16) == edge for x in range(image.width()))

    def test_the_handle_is_thin_in_both_themes(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                columns = self._handle_columns(theme)
                self.assertGreater(columns, 0, "the handle is painted in the edge color")
                self.assertLessEqual(columns, 4)

    def test_the_handle_is_three_to_one_against_the_sheet(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                tokens = tokens_for(theme)
                self.assertGreaterEqual(contrast(tokens.edge, tokens.paper), 3.0)


if __name__ == "__main__":
    unittest.main()
