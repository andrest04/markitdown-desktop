"""Files can be dropped on the drop zone and on the panes around it."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from qt_support import WindowTestCase

from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.drop_zone import FILLED_HEIGHT


def file_mime(*paths: str) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    return mime


def text_mime() -> QMimeData:
    mime = QMimeData()
    mime.setText("not a file")
    return mime


class FileDropTests(WindowTestCase):
    def _targets(self):
        return {
            "drop_zone": self.window.drop_zone,
            "left_panel": self.window.left_panel,
            "preview_panel": self.window.preview_panel,
            "table_viewport": self.window.table_view.viewport(),
        }

    def _drag_enter(self, widget, mime) -> QDragEnterEvent:
        event = QDragEnterEvent(
            QPoint(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, event)
        return event

    def _drop(self, widget, mime) -> None:
        event = QDropEvent(
            QPointF(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, event)

    def _drag_active(self) -> bool:
        return bool(self.window.drop_zone.property("dragActive"))

    def test_every_surface_accepts_a_file_drop_and_starts_conversion(self):
        for name, widget in self._targets().items():
            with self.subTest(target=name):
                source = self.make_source(f"{name}.txt")
                mime = file_mime(source)

                entered = self._drag_enter(widget, mime)
                self.assertTrue(entered.isAccepted())
                self.assertTrue(self._drag_active())

                self._drop(widget, mime)
                self.assertFalse(self._drag_active())
                self.assertTrue(self.window.model.source_exists(source))

        self.wait_started(len(self._targets()))

    def test_drag_without_urls_does_not_light_up_the_zone(self):
        for name, widget in self._targets().items():
            with self.subTest(target=name):
                self._drag_enter(widget, text_mime())
                self.assertFalse(self._drag_active())

    def test_leaving_clears_the_highlight(self):
        for name, widget in self._targets().items():
            with self.subTest(target=name):
                self._drag_enter(widget, file_mime(self.make_source("a.txt")))
                self.assertTrue(self._drag_active())
                QApplication.sendEvent(widget, QDragLeaveEvent())
                self.assertFalse(self._drag_active())

    def test_dropping_only_non_local_urls_adds_nothing(self):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/a.txt")])
        self._drag_enter(self.window.left_panel, mime)
        self._drop(self.window.left_panel, mime)
        self.assertEqual(self.window.model.items(), [])


class DropZoneRetranslateTests(WindowTestCase):
    def test_retranslate_goes_through_the_current_prominence(self):
        zone = self.window.drop_zone
        self.add_sources("a.txt")
        self.assertFalse(zone._prominent)

        i18n_manager.set_language(LANG_ES, self.window.settings)

        self.assertEqual(zone.url_edit.placeholderText(), tr("url.placeholder.filled"))
        self.assertEqual(zone.maximumHeight(), FILLED_HEIGHT)


if __name__ == "__main__":
    unittest.main()
