"""The close question follows the queue while it is open.

These run the real `exec`, whose nested event loop is what delivers worker results
while the question is on screen. A timer clicks Keep converting if the box is still
open after `PATIENCE_MS`, so a failing test fails instead of hanging.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from qt_support import FakeSettings, WindowTestCase, process_events, settle

from app.i18n import tr

PATIENCE_MS = 3000


class CloseDialogFollowsTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.settings = FakeSettings()
        self.window.show()
        self.texts: list[str] = []

    def open_box(self) -> QMessageBox | None:
        box = QApplication.activeModalWidget()
        return box if isinstance(box, QMessageBox) else None

    def click(self, key: str) -> None:
        box = self.open_box()
        if box is not None:
            next(button for button in box.buttons() if button.text() == tr(key)).click()

    def keep_after_patience(self) -> None:
        QTimer.singleShot(PATIENCE_MS, lambda: self.click("msgbox.close_busy.keep"))

    def after(self, delay_ms: int, action) -> None:
        QTimer.singleShot(delay_ms, action)

    def note_text(self) -> None:
        box = self.open_box()
        self.texts.append(box.text() if box is not None else "")

    def test_it_closes_when_the_last_conversion_finishes(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        self.keep_after_patience()
        self.after(50, lambda: self.converter.release("a.txt"))

        closed = self.window.close()

        self.assertTrue(closed)
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.open_box())
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertIn("window/geometry", self.window.settings.values)

    def test_the_count_follows_and_it_closes_after_the_last(self):
        self.add_sources("a.txt", "b.txt", "c.txt")
        self.wait_started(3)
        self.keep_after_patience()
        self.after(50, self.note_text)
        self.after(60, lambda: self.converter.release("a.txt"))
        self.after(250, self.note_text)
        self.after(260, lambda: self.converter.release("b.txt"))
        self.after(450, self.note_text)
        self.after(460, lambda: self.converter.release("c.txt"))

        closed = self.window.close()

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

    def test_keep_after_a_partial_change_keeps_the_window(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)
        self.after(50, lambda: self.converter.release("a.txt"))
        self.after(250, lambda: self.click("msgbox.close_busy.keep"))

        self.assertFalse(self.window.close())

        self.assertTrue(self.window.isVisible())
        self.converter.release("b.txt")
        settle()
        self.assertEqual(self.downloaded_names(), ["a.md", "b.md"])
        self.assertTrue(self.window.isVisible())

    def test_keep_is_not_overruled_by_a_batch_finishing_later(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        self.after(50, lambda: self.click("msgbox.close_busy.keep"))
        self.assertFalse(self.window.close())

        self.converter.release("a.txt")
        settle()
        process_events()

        self.assertTrue(self.window.isVisible())

    def test_close_anyway_still_closes_with_work_left(self):
        self.add_sources("a.txt", "b.txt")
        self.wait_started(2)
        self.after(50, lambda: self.click("msgbox.close_busy.close"))

        self.assertTrue(self.window.close())

        self.assertEqual(self.downloaded_names(), [])
