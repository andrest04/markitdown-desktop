"""Converting again replaces the text, so edits no file holds are asked about first.

The question never opens: `QMessageBox.exec` is replaced by a stand-in that records
the box and clicks one of its buttons.
"""
from __future__ import annotations

from unittest import mock

from PySide6.QtWidgets import QDialog, QMessageBox
from qt_support import WindowTestCase, pump_until, settle

from app.core.queue_model import DisplayState
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog

EDIT = "# my careful edit"


class EditPromptTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.shown: list[dict] = []
        self.answer = "msgbox.replace_edits.keep"

        def exec_stand_in(box):
            buttons = {button.text(): button for button in box.buttons()}
            self.shown.append(
                {
                    "text": box.text(),
                    "buttons": sorted(buttons),
                    "default": box.defaultButton().text(),
                    "escape": box.escapeButton().text(),
                }
            )
            buttons[tr(self.answer)].click()
            return 0

        patcher = mock.patch.object(QMessageBox, "exec", exec_stand_in)
        patcher.start()
        self.addCleanup(patcher.stop)

    def saved_item(self):
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        item = self.item_named("a.txt")
        self.assertTrue(pump_until(lambda: item.display_state == DisplayState.SAVED))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        return item

    def change_hints(self, charset: str = "cp1252") -> None:
        def accepted(dialog):
            dialog.charset_override_edit.setText(charset)
            return QDialog.DialogCode.Accepted

        self.converter.release_all()
        with mock.patch.object(AdvancedSettingsDialog, "exec", accepted):
            self.window._show_advanced_settings()
        settle()

    def test_no_edits_no_question(self):
        self.saved_item()
        self.change_hints()
        self.assertEqual(self.shown, [])
        self.assertEqual(self.converter.call_count("a.txt"), 2)

    def test_an_edit_undone_is_no_edit(self):
        item = self.saved_item()
        original = item.markdown_result
        self.window.raw_view.setPlainText(EDIT)
        self.window.raw_view.setPlainText(original)
        self.change_hints()
        self.assertEqual(self.shown, [])

    def test_declining_keeps_the_edit_and_the_hints_and_converts_nothing(self):
        item = self.saved_item()
        self.window.raw_view.setPlainText(EDIT)

        self.change_hints()

        self.assertEqual(len(self.shown), 1)
        self.assertEqual(item.markdown_result, EDIT)
        self.assertEqual(self.window.raw_view.toPlainText(), EDIT)
        self.assertEqual(item.charset_override, "cp1252")
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.downloaded_names(), ["a.md"])

    def test_not_converting_is_the_easy_answer(self):
        self.saved_item()
        self.window.raw_view.setPlainText(EDIT)
        self.change_hints()
        shown = self.shown[0]
        self.assertEqual(shown["default"], tr("msgbox.replace_edits.keep"))
        self.assertEqual(shown["escape"], tr("msgbox.replace_edits.keep"))
        self.assertEqual(
            shown["buttons"], sorted([tr("msgbox.replace_edits.keep"), tr("msgbox.replace_edits.convert")])
        )

    def test_accepting_converts_as_usual(self):
        item = self.saved_item()
        self.window.raw_view.setPlainText(EDIT)
        self.answer = "msgbox.replace_edits.convert"

        self.change_hints()

        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(item.markdown_result, "# converted a.txt")
        self.assertEqual(self.downloaded_names(), ["a (1).md", "a.md"])

    def test_the_question_follows_the_language(self):
        self.saved_item()
        self.window.raw_view.setPlainText(EDIT)
        i18n_manager._language = LANG_ES
        self.change_hints()
        self.assertIn("ediciones", self.shown[0]["text"])

    def test_unchanged_hints_ask_nothing_however_edited(self):
        self.saved_item()
        self.window.raw_view.setPlainText(EDIT)
        self.change_hints("")
        self.assertEqual(self.shown, [])
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def failed_save(self):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError("no room")):
            self.add_sources("a.txt")
            self.converter.release("a.txt")
            item = self.item_named("a.txt")
            self.assertTrue(pump_until(lambda: item.display_state == DisplayState.SAVE_FAILED))
        self.window.table_view.selectRow(0)
        self.window._refresh_preview()
        return item

    def test_a_failed_save_without_edits_asks_nothing(self):
        self.failed_save()
        self.change_hints()
        self.assertEqual(self.shown, [])
        self.assertEqual(self.converter.call_count("a.txt"), 2)

    def test_a_failed_save_with_edits_asks(self):
        item = self.failed_save()
        self.window.raw_view.setPlainText(EDIT)
        self.change_hints()
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(item.markdown_result, EDIT)
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_edits_saved_by_a_retry_are_no_longer_at_risk(self):
        self.failed_save()
        self.window.raw_view.setPlainText(EDIT)
        self.window._start_conversion([0])
        self.change_hints()
        self.assertEqual(self.shown, [])
        self.assertEqual(self.converter.call_count("a.txt"), 2)
