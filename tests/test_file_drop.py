"""Files can be dropped on the drop zone and on the panes around it."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from qt_support import WindowTestCase, process_events, settle

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


def send_drag_enter(widget, mime: QMimeData) -> QDragEnterEvent:
    event = QDragEnterEvent(
        QPoint(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)
    return event


def send_drop(widget, mime: QMimeData) -> None:
    event = QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


class FileDropTests(WindowTestCase):
    def _targets(self):
        return {
            "drop_zone": self.window.drop_zone,
            "left_panel": self.window.left_panel,
            "preview_panel": self.window.preview_panel,
            "table_viewport": self.window.table_view.viewport(),
        }

    def _drag_enter(self, widget, mime) -> QDragEnterEvent:
        return send_drag_enter(widget, mime)

    def _drop(self, widget, mime) -> None:
        send_drop(widget, mime)

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


class DropFocusTests(WindowTestCase):
    """After a drop, Delete acts on the selected row, unless focus is busy elsewhere."""

    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        self.window.activateWindow()
        self.window.centralWidget().setFocus()
        process_events()
        if QApplication.focusWidget() is not self.window.centralWidget():
            self.skipTest("this platform plugin gives the window no focus")

    def _drop_file(self, name):
        # Qt only delivers a drop to the widget that accepted the drag.
        mime = file_mime(self.make_source(name))
        send_drag_enter(self.window.left_panel, mime)
        send_drop(self.window.left_panel, mime)
        process_events()
        self.assertIn(name, self._names())

    def _names(self):
        return [item.display_name for item in self.window.model.items()]

    def _press_delete(self):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Delete)
        process_events()

    def test_delete_removes_the_row_a_drop_selected(self):
        self._drop_file("a.txt")
        self._press_delete()
        self.assertEqual(self._names(), [])

    def test_delete_removes_it_after_its_conversion_finished(self):
        self._drop_file("a.txt")
        self.wait_started(1)
        self.converter.release("a.txt")
        settle()
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self._press_delete()
        self.assertEqual(self._names(), [])

    def test_a_later_drop_leaves_delete_on_the_selected_row(self):
        self._drop_file("a.txt")
        self.window.centralWidget().setFocus()
        self._drop_file("b.txt")
        self._press_delete()
        self.assertEqual(self._names(), ["b.txt"])

    def test_a_drop_takes_focus_from_a_button(self):
        self._drop_file("a.txt")
        self.window.add_files_btn.setFocus()
        self._drop_file("b.txt")
        self.assertIs(QApplication.focusWidget(), self.window.table_view)

    def test_the_link_field_keeps_focus_and_its_delete_key(self):
        field = self.window.url_edit
        field.setFocus()
        field.setText("abc")
        field.setCursorPosition(0)
        self._drop_file("a.txt")
        self.assertIs(QApplication.focusWidget(), field)
        self._press_delete()
        self.assertEqual(field.text(), "bc")
        self.assertEqual(self._names(), ["a.txt"])

    def test_the_markdown_tab_keeps_focus(self):
        self._drop_file("a.txt")
        window = self.window
        window.tabs.setCurrentWidget(window.raw_view)
        window.preview_body.setVisible(True)
        process_events()
        window.raw_view.setFocus()
        self._drop_file("b.txt")
        self.assertIs(QApplication.focusWidget(), window.raw_view)

    def test_an_open_dialog_keeps_focus(self):
        for modal in (True, False):
            with self.subTest(modal=modal):
                dialog = QDialog(self.window)
                self.addCleanup(dialog.deleteLater)
                self.addCleanup(dialog.close)
                dialog.setModal(modal)
                field = QLineEdit(dialog)
                dialog.show()
                dialog.activateWindow()
                field.setFocus()
                process_events()
                if QApplication.focusWidget() is not field:
                    self.skipTest("this platform plugin gives a dialog no focus")
                self._drop_file(f"modal_{modal}.txt")
                self.assertIs(QApplication.focusWidget(), field)
                self.assertIsNot(self.window.focusWidget(), self.window.table_view)
                dialog.close()
                self.window.activateWindow()
                self.window.centralWidget().setFocus()
                process_events()

    def test_adding_through_the_buttons_leaves_focus_alone(self):
        self.add_sources("a.txt")
        self.window.add_files_btn.setFocus()
        self.add_sources("b.txt")
        process_events()
        self.assertIs(QApplication.focusWidget(), self.window.add_files_btn)


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
