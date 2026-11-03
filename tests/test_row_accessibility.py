"""The queue works without a mouse and says what it shows to assistive technology."""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QHelpEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from qt_support import WindowTestCase, process_events, pump_until

from app.core.queue_model import (
    COLUMN_NAME,
    COLUMN_STATUS,
    FailureReason,
    ItemStatus,
    QueueItem,
    SourceKind,
)
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager


def make_item(name="a.txt", status=ItemStatus.PENDING, **fields) -> QueueItem:
    return QueueItem(source=f"/somewhere/{name}", kind=SourceKind.FILE, display_name=name, status=status, **fields)


def failed(name="a.txt", message="boom", reason=FailureReason.UNREADABLE_FILE) -> QueueItem:
    return make_item(name, ItemStatus.ERROR, error_message=message, error_reason=reason)


def not_saved(name="b.txt") -> QueueItem:
    return make_item(
        name, ItemStatus.DONE, save_error="No space left", save_error_reason=FailureReason.DISK_FULL, markdown_result="#"
    )


def saved(name="c.txt") -> QueueItem:
    return make_item(name, ItemStatus.DONE, saved_path=f"/x/{name}.md", markdown_result="#")


class RowTestCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        process_events()

    def add(self, *items):
        for item in items:
            self.window.model.add_item(item)
        self.window._update_drop_zone_prominence()
        process_events()

    def press(self, key, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.window.table_view, key, modifier)


class KeyboardRetryTests(RowTestCase):
    def _focus_row(self, row):
        view = self.window.table_view
        view.setFocus()
        view.setCurrentIndex(self.window.model.index(row, 0))

    def test_enter_on_a_failed_row_retries_it(self):
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            with self.subTest(key=key):
                self.window.model.clear()
                self.converter.calls.clear()
                self.add(failed("a.txt"), failed("b.txt"))
                self._focus_row(1)
                self.press(key)
                self.assertTrue(pump_until(lambda: self.converter.call_count("b.txt") == 1))
                self.assertEqual(self.converter.call_count("a.txt"), 0)
                self.converter.release("b.txt")

    def test_enter_retries_a_row_that_could_not_save(self):
        self.add(not_saved("b.txt"))
        self._focus_row(0)
        self.press(Qt.Key.Key_Return)
        self.assertTrue(pump_until(lambda: self.converter.call_count("b.txt") == 1))

    def test_enter_does_nothing_on_a_row_that_is_fine(self):
        self.add(saved(), make_item("d.txt", ItemStatus.CONVERTING))
        for row in (0, 1):
            with self.subTest(row=row):
                self._focus_row(row)
                self.press(Qt.Key.Key_Return)
                process_events()
                self.assertEqual(self.converter.call_count(), 0)

    def test_enter_with_no_focused_row_does_nothing(self):
        self.add(failed())
        self.window.table_view.setCurrentIndex(self.window.model.index(-1, -1))
        self.press(Qt.Key.Key_Return)
        process_events()
        self.assertEqual(self.converter.call_count(), 0)

    def test_enter_acts_on_the_focused_row_of_a_multi_selection(self):
        self.add(failed("a.txt"), failed("b.txt"))
        view = self.window.table_view
        view.selectAll()
        self._focus_row(0)
        view.selectAll()
        self.press(Qt.Key.Key_Return)
        self.assertTrue(pump_until(lambda: self.converter.call_count("a.txt") == 1))
        self.assertEqual(self.converter.call_count("b.txt"), 0)

    def test_tab_leaves_the_list_instead_of_walking_its_cells(self):
        self.add(failed("a.txt"), failed("b.txt"))
        view = self.window.table_view
        self.assertFalse(view.tabKeyNavigation())
        self.window.activateWindow()
        view.setFocus()
        process_events()
        if QApplication.focusWidget() is not view:
            self.skipTest("this platform plugin gives the window no focus")
        self.press(Qt.Key.Key_Tab)
        process_events()
        self.assertIsNot(QApplication.focusWidget(), view)

    def test_the_key_is_documented_on_the_row_it_works_on(self):
        from app.ui.queue_delegate import row_tooltip

        self.assertIn(tr("row.retry_hint"), row_tooltip(failed()))
        self.assertIn(tr("row.retry_hint"), row_tooltip(not_saved()))

    def test_the_row_action_keeps_its_place_and_size(self):
        from PySide6.QtCore import QRect

        from app.ui.queue_delegate import ROW_HEIGHT, retry_rect

        rect = retry_rect(QRect(0, 0, 340, ROW_HEIGHT), failed())
        self.assertEqual((rect.width(), rect.height()), (76, 26))


class AccessibleTextTests(RowTestCase):
    def _text(self, row=0):
        return self.window.model.data(self.window.model.index(row, COLUMN_NAME), Qt.ItemDataRole.AccessibleTextRole)

    def test_a_row_says_its_name_and_status(self):
        self.add(make_item("a.txt"), saved("c.txt"), failed("d.txt"), not_saved("e.txt"))
        self.assertEqual(self._text(0), "a.txt, Waiting")
        self.assertEqual(self._text(1), "c.txt, Saved to Downloads")
        self.assertEqual(self._text(2), "d.txt, Failed: damaged or unreadable file")
        self.assertEqual(self._text(3), "e.txt, Not saved: disk full")

    def test_it_follows_a_live_language_switch(self):
        self.add(failed("d.txt"))
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertEqual(self._text(), "d.txt, Falló: archivo dañado o ilegible")

    def test_only_a_row_that_can_retry_mentions_the_key(self):
        self.add(failed(), saved())
        model = self.window.model
        description = Qt.ItemDataRole.AccessibleDescriptionRole
        self.assertEqual(model.data(model.index(0, COLUMN_NAME), description), tr("row.retry_hint"))
        self.assertIsNone(model.data(model.index(1, COLUMN_NAME), description))

    def test_the_accessibility_tree_reports_it(self):
        self.add(failed("d.txt"))
        view = QAccessible.queryAccessibleInterface(self.window.table_view)
        self.assertIsNotNone(view)
        names = [view.child(i).text(QAccessible.Text.Name) for i in range(view.childCount())]
        self.assertIn("d.txt, Failed: damaged or unreadable file", names)


class ExitShortcutTests(RowTestCase):
    def test_the_menu_shows_a_real_key_on_every_platform(self):
        # Qt's StandardKey.Quit is the literal Key_Exit on Windows.
        shortcut = self.window.exit_action.shortcut()
        self.assertEqual(shortcut, QKeySequence("Ctrl+Q"))
        self.assertNotEqual(shortcut.toString(), "Exit")


class TooltipTests(RowTestCase):
    def _tooltip_shown(self, row=0):
        view = self.window.table_view
        cell = view.visualRect(self.window.model.index(row, 0))
        event = QHelpEvent(QHelpEvent.Type.ToolTip, cell.center(), view.viewport().mapToGlobal(cell.center()))
        option = QStyleOptionViewItem()
        with mock.patch("app.ui.queue_delegate.QToolTip.showText") as show:
            handled = self.window.queue_delegate.helpEvent(event, view, option, self.window.model.index(row, 0))
        return handled, show

    def test_the_hidden_status_column_has_no_tooltips_left(self):
        for item in (failed(), not_saved(), saved(), make_item()):
            with self.subTest(state=item.display_state):
                self.window.model.clear()
                self.add(item)
                index = self.window.model.index(0, COLUMN_STATUS)
                self.assertIsNone(self.window.model.data(index, Qt.ItemDataRole.ToolTipRole))

    def test_the_name_column_still_gives_the_source(self):
        self.add(saved("c.txt"))
        index = self.window.model.index(0, COLUMN_NAME)
        self.assertEqual(self.window.model.data(index, Qt.ItemDataRole.ToolTipRole), "/somewhere/c.txt")

    def test_a_failed_row_gives_the_whole_reason_and_the_raw_text(self):
        from app.ui.queue_delegate import row_tooltip

        text = row_tooltip(failed(message="File conversion failed after 1 attempts"))
        self.assertIn(tr("error.unreadable_file"), text.lower())
        self.assertIn("File conversion failed after 1 attempts", text)

    def test_a_row_that_could_not_save_gives_the_reason_and_the_raw_text(self):
        from app.ui.queue_delegate import row_tooltip

        text = row_tooltip(not_saved())
        self.assertIn(tr("error.disk_full"), text)
        self.assertIn("No space left", text)

    def test_a_very_long_raw_message_is_cut(self):
        from app.ui.queue_delegate import row_tooltip

        self.assertLess(len(row_tooltip(failed(message="x" * 5000))), 1000)

    def test_a_row_that_is_fine_has_no_problem_tooltip(self):
        from app.ui.queue_delegate import row_tooltip

        self.assertEqual(row_tooltip(saved()), "")
        self.assertEqual(row_tooltip(make_item()), "")

    def test_hovering_a_problem_row_shows_it(self):
        from app.ui.queue_delegate import row_tooltip

        self.add(failed())
        handled, show = self._tooltip_shown()
        self.assertTrue(handled)
        self.assertEqual(show.call_args.args[1], row_tooltip(self.window.model.item_at(0)))


if __name__ == "__main__":
    unittest.main()
