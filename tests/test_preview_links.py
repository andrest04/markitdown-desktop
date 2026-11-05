"""A link in converted text may scroll or leave for a browser, never replace the preview.

Links are clicked for real, because `QTextBrowser` decides what a click does. Opens
are caught by Qt's own URL handlers, so no test can start a real browser.
"""
from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QImage, QTextCursor, QTextDocument
from PySide6.QtTest import QTest
from qt_support import WindowTestCase, process_events, pump_until

from app.core.queue_model import ItemStatus

EXTERNAL_SCHEMES = ("http", "https", "mailto", "file")


class _OpenedUrls(QObject):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    @Slot(QUrl)
    def record(self, url: QUrl) -> None:
        self.urls.append(url.toString())


class PreviewTestCase(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opened = _OpenedUrls()
        for scheme in EXTERNAL_SCHEMES:
            QDesktopServices.setUrlHandler(scheme, self.opened, "record")
            self.addCleanup(QDesktopServices.unsetUrlHandler, scheme)

        self.window.resize(900, 500)
        self.window.show()
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
        self.view = self.window.rendered_view

    def show_markdown(self, text: str) -> None:
        self.item_named("a.txt").markdown_result = text
        self.window._refresh_preview()
        process_events()


class LinkTests(PreviewTestCase):
    def click_link(self, href: str) -> None:
        cursor = QTextCursor(self.view.document())
        for position in range(self.view.document().characterCount() - 1):
            cursor.setPosition(position)
            cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
            if cursor.charFormat().anchorHref() == href:
                cursor.setPosition(position)
                break
        else:
            self.fail(f"no link to {href} in the preview")
        point = self.view.cursorRect(cursor).center() + QPoint(3, 0)
        self.assertEqual(self.view.anchorAt(point), href)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        process_events()

    def assert_click_changes_nothing(self, href: str) -> None:
        self.show_markdown(f"Some text with [a link]({href}) in it.")
        before = self.view.toPlainText()
        self.assertIn("Some text", before)

        self.click_link(href)

        self.assertEqual(self.view.toPlainText(), before)
        self.assertTrue(self.view.source().isEmpty())
        self.assertEqual(self.opened.urls, [])

    def test_a_relative_link_leaves_the_preview_intact(self):
        self.assert_click_changes_nothing("/wiki/Foo")

    def test_a_relative_link_with_a_fragment_leaves_the_preview_intact(self):
        self.assert_click_changes_nothing("other.md#sec")

    def test_a_link_to_a_local_file_does_not_load_it(self):
        with tempfile.TemporaryDirectory() as folder:
            secret = Path(folder) / "secret.txt"
            secret.write_text("the secret", encoding="utf-8")
            self.assert_click_changes_nothing(secret.as_uri())

    def test_other_schemes_do_nothing(self):
        for href in ("javascript:alert(1)", "ftp://example.invalid/a", "http:no-host", "qrc:/a"):
            with self.subTest(href=href):
                self.assert_click_changes_nothing(href)

    def test_web_and_mail_links_open_outside_the_app(self):
        for href in ("http://example.invalid/a", "https://example.invalid/b?x=1#c", "mailto:someone@example.invalid"):
            with self.subTest(href=href):
                self.opened.urls.clear()
                self.show_markdown(f"Some text with [a link]({href}) in it.")
                before = self.view.toPlainText()

                self.click_link(href)

                self.assertEqual(self.opened.urls, [href])
                self.assertEqual(self.view.toPlainText(), before)

    def test_a_fragment_scrolls_to_its_anchor(self):
        filler = "\n\n".join(f"Paragraph {number}" for number in range(200))
        self.show_markdown(f'[go down](#sec)\n\n{filler}\n\n<a name="sec"></a>The end')
        before = self.view.toPlainText()
        bar = self.view.verticalScrollBar()
        self.assertEqual(bar.value(), 0)

        self.click_link("#sec")

        self.assertGreater(bar.value(), 0)
        self.assertEqual(self.view.toPlainText(), before)
        self.assertEqual(self.opened.urls, [])


class ImageTests(PreviewTestCase):
    """Whatever converted text names must not make the app read files or shares."""

    def setUp(self) -> None:
        super().setUp()
        self.image_path = self.tmp / "secret.png"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)
        self.assertTrue(image.save(str(self.image_path)))

    def shown_size(self, src: str) -> tuple[int, int]:
        self.show_markdown(f"Before\n\n![picture]({src})\n\nAfter")
        self.view.viewport().grab()
        size = self.view.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(src)).size()
        return size.width(), size.height()

    def test_local_images_are_not_loaded(self):
        for src in (self.image_path.as_uri(), self.image_path.as_posix()):
            with self.subTest(src=src):
                self.assertEqual(self.shown_size(src), (1, 1))

    def test_an_image_on_a_share_is_not_loaded(self):
        src = "file://nonexistent.invalid/share/x.png"
        self.assertEqual(self.shown_size(src), (1, 1))

    def test_images_embedded_in_the_text_still_show(self):
        # What "keep data URIs" produces.
        encoded = base64.b64encode(self.image_path.read_bytes()).decode()
        self.assertEqual(self.shown_size(f"data:image/png;base64,{encoded}"), (40, 30))

    def test_a_local_stylesheet_is_not_read(self):
        sheet = self.tmp / "sheet.css"
        sheet.write_text("p { color: red }", encoding="utf-8")
        loaded = self.view.loadResource(
            QTextDocument.ResourceType.StyleSheetResource.value,
            QUrl.fromLocalFile(str(sheet)),
        )
        self.assertEqual(loaded, "")
        self.show_markdown(f'<link rel="stylesheet" href="{sheet.as_uri()}">\n\nStill here')
        self.assertIn("Still here", self.view.toPlainText())


if __name__ == "__main__":
    unittest.main()
