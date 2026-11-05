"""Changing an item's hints in Advanced settings converts a finished item again.

The dialog is never opened: `exec` is replaced by a stand-in that edits the fields
the way a person would and accepts. One test runs the real `convert_item`, because
the point of the hint is the text that comes out.
"""
from __future__ import annotations

import errno
from unittest import mock

from PySide6.QtWidgets import QDialog
from qt_support import WindowTestCase, pump_until, settle

from app.core.converter import convert_item as real_convert_item
from app.core.queue_model import DisplayState, ItemStatus
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog


class HintTestCase(WindowTestCase):
    def accept_dialog(self, edit=None) -> None:
        """Run Advanced settings on the selected row: `edit(dialog)`, then accept."""

        def exec_stand_in(dialog):
            if edit is not None:
                edit(dialog)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AdvancedSettingsDialog, "exec", exec_stand_in):
            self.window._show_advanced_settings()

    @staticmethod
    def set_charset(value: str):
        return lambda dialog: dialog.charset_override_edit.setText(value)

    def saved_item(self, name: str = "a.txt"):
        self.add_sources(name)
        self.converter.release(name)
        self.assertTrue(pump_until(lambda: self.item_named(name).display_state == DisplayState.SAVED))
        return self.item_named(name)


class HintsOnASavedItemTests(HintTestCase):
    def test_changed_hints_convert_again_and_keep_the_earlier_file(self):
        item = self.saved_item()
        first_file = item.saved_path

        self.converter.release_all()
        self.accept_dialog(self.set_charset("cp1252"))
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(item.charset_override, "cp1252")
        self.assertEqual(self.downloaded_names(), ["a (1).md", "a.md"])
        self.assertEqual(item.display_state, DisplayState.SAVED)
        self.assertNotEqual(item.saved_path, first_file)

    def test_the_mime_type_and_extension_hints_count_as_well(self):
        for name, field in (("a.txt", "mimetype_override_edit"), ("b.txt", "extension_override_edit")):
            with self.subTest(field=field):
                self.window.table_view.clearSelection()
                self.saved_item(name)
                self.window.table_view.selectRow(self.window.model.row_of(self.item_named(name)))
                self.converter.release_all()
                self.accept_dialog(lambda dialog, field=field: getattr(dialog, field).setText("x"))
                settle()
                self.converter.hold_all()
                self.assertEqual(self.converter.call_count(name), 2)

    def test_unchanged_hints_do_nothing(self):
        self.saved_item()
        self.accept_dialog()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.downloaded_names(), ["a.md"])

    def test_only_surrounding_spaces_is_not_a_change(self):
        # convert_item strips hints, so this would convert to the same text.
        item = self.saved_item()
        self.accept_dialog(self.set_charset("  "))
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(item.display_state, DisplayState.SAVED)

    def test_options_that_are_not_hints_do_not_convert(self):
        self.saved_item()
        self.accept_dialog(lambda dialog: dialog.enable_plugins_cb.setChecked(True))
        settle()
        self.assertTrue(self.window.conversion_options.enable_plugins)
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_cancelling_changes_nothing(self):
        item = self.saved_item()

        def rejected(dialog):
            dialog.charset_override_edit.setText("cp1252")
            return QDialog.DialogCode.Rejected

        with mock.patch.object(AdvancedSettingsDialog, "exec", rejected):
            self.window._show_advanced_settings()
        settle()
        self.assertEqual(item.charset_override, "")
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_it_converts_with_the_options_just_accepted(self):
        self.saved_item()

        def edit(dialog):
            dialog.charset_override_edit.setText("cp1252")
            dialog.enable_plugins_cb.setChecked(True)

        self.converter.release_all()
        self.accept_dialog(edit)
        settle()
        self.assertTrue(self.converter.options_seen[-1].enable_plugins)

    def test_it_acts_on_the_item_the_dialog_named(self):
        self.add_sources("a.txt", "b.txt")
        self.converter.release_all()
        settle()
        self.converter.hold_all()
        self.window.table_view.selectRow(1)

        self.converter.release_all()
        self.accept_dialog(self.set_charset("cp1252"))
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.converter.call_count("b.txt"), 2)


class HintsOnOtherStatesTests(HintTestCase):
    def test_hints_on_an_item_being_converted_are_kept_without_a_second_worker(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.CONVERTING))

        self.accept_dialog(self.set_charset("cp1252"))

        self.assertEqual(self.item_named("a.txt").charset_override, "cp1252")
        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.downloaded_names(), ["a.md"])

    def test_changing_hints_again_while_converting_again_does_not_double_convert(self):
        item = self.saved_item()
        self.accept_dialog(self.set_charset("cp1252"))
        self.assertTrue(pump_until(lambda: self.converter.call_count("a.txt") == 2))

        self.accept_dialog(self.set_charset("cp850"))

        self.assertEqual(item.charset_override, "cp850")
        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(self.downloaded_names(), ["a (1).md", "a.md"])

    def test_a_failed_item_keeps_waiting_for_retry(self):
        self.converter.failures["a.txt"] = "boom"
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR))

        self.accept_dialog(self.set_charset("cp1252"))
        settle()

        self.assertEqual(self.item_named("a.txt").charset_override, "cp1252")
        self.assertEqual(self.converter.call_count("a.txt"), 1)

    def test_a_save_failed_item_converts_again_since_the_text_it_holds_lacks_the_hint(self):
        with mock.patch("app.core.conversion_queue.auto_save_markdown", side_effect=OSError(errno.ENOSPC, "No space")):
            self.add_sources("a.txt")
            self.converter.release("a.txt")
            self.assertTrue(
                pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVE_FAILED)
            )

        self.converter.release_all()
        self.accept_dialog(self.set_charset("cp1252"))
        settle()

        self.assertEqual(self.converter.call_count("a.txt"), 2)
        self.assertEqual(self.item_named("a.txt").display_state, DisplayState.SAVED)
        self.assertEqual(self.downloaded_names(), ["a.md"])


class RealConversionTests(HintTestCase):
    def test_the_charset_hint_fixes_the_saved_text(self):
        # Short enough that detection guesses wrong, as in the reported file.
        source = self.sources / "a.txt"
        source.write_bytes("España café mañana".encode("cp1252"))

        with mock.patch("app.core.converter.convert_item", real_convert_item):
            self.window._add_paths([str(source)])
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").display_state == DisplayState.SAVED, 30))
            first = (self.downloads / "a.md").read_text(encoding="utf-8")
            self.assertNotEqual(first, "España café mañana")

            self.accept_dialog(self.set_charset("cp1252"))
            self.assertTrue(pump_until(lambda: (self.downloads / "a (1).md").exists(), 30))
            settle()

        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), first)
        self.assertEqual((self.downloads / "a (1).md").read_text(encoding="utf-8"), "España café mañana")
        self.assertEqual(self.item_named("a.txt").markdown_result, "España café mañana")
