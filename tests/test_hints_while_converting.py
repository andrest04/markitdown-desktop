"""Hints accepted during a conversion it may have already read: convert once more after."""
from __future__ import annotations

from unittest import mock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QMessageBox
from qt_support import WindowTestCase, process_events, pump_until, settle

from app.core.queue_model import DisplayState, ItemStatus
from app.i18n import tr
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog


class WhileConvertingTestCase(WindowTestCase):
    def change_hints(self, charset: str = "cp1252") -> None:
        def accepted(dialog):
            dialog.charset_override_edit.setText(charset)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AdvancedSettingsDialog, "exec", accepted):
            self.window._show_advanced_settings()

    def converting_item(self, name: str = "a.txt"):
        self.add_sources(name)
        item = self.item_named(name)
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.CONVERTING))
        return item

    def answer_questions_with(self, key: str) -> list[str]:
        shown: list[str] = []

        def exec_stand_in(box):
            shown.append(box.text())
            next(button for button in box.buttons() if button.text() == tr(key)).click()
            return 0

        patcher = mock.patch.object(QMessageBox, "exec", exec_stand_in)
        patcher.start()
        self.addCleanup(patcher.stop)
        return shown

    def wait_for_conversions(self, count: int, name: str = "a.txt") -> None:
        self.assertTrue(pump_until(lambda: self.converter.call_count(name) == count))


class ConvertsOnceMoreTests(WhileConvertingTestCase):
    def test_it_converts_once_more_after_the_running_one_ends(self):
        item = self.converting_item()
        self.change_hints()
        process_events()
        self.assertEqual(self.converter.call_count("a.txt"), 1)

        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: (self.downloads / "a.md").exists()))
        self.wait_for_conversions(2)
        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: (self.downloads / "a (1).md").exists()))
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(item.display_state, DisplayState.SAVED)
        self.assertEqual(self.downloaded_names(), ["a (1).md", "a.md"])

    def test_it_stops_there(self):
        self.converting_item()
        self.change_hints()
        self.converter.release_all()
        self.wait_for_conversions(2)
        settle()
        for _ in range(3):
            settle()
        self.assertEqual(self.converter.call_count("a.txt"), 2)

    def test_changing_them_twice_during_one_conversion_converts_once_more(self):
        item = self.converting_item()
        self.change_hints("cp1252")
        self.change_hints("cp850")
        self.converter.release_all()
        self.wait_for_conversions(2)
        settle()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(item.charset_override, "cp850")

    def test_changing_them_again_during_the_extra_one_converts_again(self):
        self.converting_item()
        self.change_hints("cp1252")
        self.converter.release("a.txt")
        self.wait_for_conversions(2)
        self.change_hints("cp850")
        self.converter.release_all()
        self.wait_for_conversions(3)
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 3)

    def test_unchanged_hints_do_not(self):
        self.converting_item()
        self.change_hints("")
        self.converter.release_all()
        settle()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_a_conversion_that_fails_under_the_old_hints_converts_once_more(self):
        item = self.converting_item()
        self.converter.failures["a.txt"] = "boom"
        self.change_hints()
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR))
        del self.converter.failures["a.txt"]
        self.wait_for_conversions(2)
        self.converter.release_all()
        self.assertTrue(pump_until(lambda: (self.downloads / "a.md").exists()))
        settle()
        self.assertEqual(item.display_state, DisplayState.SAVED)

    def test_a_worker_not_started_yet_reads_them_itself(self):
        pool = QThreadPool.globalInstance()
        previous = pool.maxThreadCount()
        pool.setMaxThreadCount(1)
        self.addCleanup(pool.setMaxThreadCount, previous)
        self.add_sources("a.txt", "b.txt")
        self.wait_started(1)
        self.window.table_view.selectRow(1)
        self.assertEqual(self.item_named("b.txt").status, ItemStatus.PENDING)

        self.change_hints()
        self.converter.release_all()
        self.wait_for_conversions(1, "b.txt")
        settle()
        settle()

        self.assertEqual(self.converter.call_count("b.txt"), 1)
        self.assertEqual(self.item_named("b.txt").charset_override, "cp1252")


class SameRuleAsEditsTests(WhileConvertingTestCase):
    def failed_item_holding_an_edit(self):
        """Saved, edited, then converted again by choice, with hints changed on the way."""
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        item = self.item_named("a.txt")
        self.assertTrue(pump_until(lambda: item.display_state == DisplayState.SAVED))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        self.window.raw_view.setPlainText("# my edit")
        self.converter.failures["a.txt"] = "boom"
        self.window.conversion_queue.enqueue([item], self.window.conversion_options)
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.CONVERTING))
        self.change_hints()
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR))
        return item

    def test_declining_keeps_the_edit_and_converts_nothing(self):
        shown = self.answer_questions_with("msgbox.replace_edits.keep")
        item = self.failed_item_holding_an_edit()
        self.assertTrue(pump_until(lambda: len(shown) == 1))
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(item.markdown_result, "# my edit")
        self.assertEqual(item.charset_override, "cp1252")

    def test_accepting_converts_once_more(self):
        shown = self.answer_questions_with("msgbox.replace_edits.convert")
        self.failed_item_holding_an_edit()
        del self.converter.failures["a.txt"]
        self.assertTrue(pump_until(lambda: len(shown) == 1))
        self.wait_for_conversions(3)


class ItemGoneTests(WhileConvertingTestCase):
    def test_a_removed_item_is_not_converted_again(self):
        self.converting_item()
        self.change_hints()
        self.window.table_view.selectRow(0)
        self.window.action_remove_selected()
        self.converter.release_all()
        settle()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.downloaded_names(), [])

    def test_a_window_closed_meanwhile_starts_nothing(self):
        self.window.show()
        self.converting_item()
        self.change_hints()
        due: list = []
        self.window.conversion_queue.conversion_again_due.connect(due.append)
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: bool(due)))

        # The extra conversion is one event loop turn away, and the window closes first.
        self.window.close()
        settle()
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 1)
