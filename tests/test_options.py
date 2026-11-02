"""One ConversionOptions value, passed around instead of mirrored field by field."""
from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QDialog
from qt_support import WindowTestCase, process_events, qapp, settle

from app.core.converter import ConversionOptions
from app.core.queue_model import QueueItem, SourceKind

REPO_ROOT = Path(__file__).resolve().parent.parent

NON_DEFAULT = ConversionOptions(
    enable_plugins=True,
    keep_data_uris=True,
    docintel_enabled=True,
    docintel_endpoint="https://docintel.example",
    cu_enabled=True,
    cu_endpoint="https://cu.example",
    cu_analyzer_id="analyzer",
)


def make_item() -> QueueItem:
    return QueueItem(
        source="/somewhere/a.txt",
        kind=SourceKind.FILE,
        display_name="a.txt",
        extension_override=".md",
        mimetype_override="text/plain",
        charset_override="utf-8",
    )


class OptionsValueTests(unittest.TestCase):
    def test_options_cannot_be_mutated(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ConversionOptions().enable_plugins = True

    def test_every_field_differs_from_its_default_in_the_fixture(self):
        defaults = ConversionOptions()
        for field in dataclasses.fields(ConversionOptions):
            with self.subTest(field=field.name):
                self.assertNotEqual(getattr(NON_DEFAULT, field.name), getattr(defaults, field.name))


class DialogTests(unittest.TestCase):
    def setUp(self) -> None:
        qapp()

    def _dialog(self, *args):
        from app.ui.advanced_settings_dialog import AdvancedSettingsDialog

        dialog = AdvancedSettingsDialog(*args)
        self.addCleanup(process_events)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_round_trip_keeps_every_field(self):
        self.assertEqual(self._dialog(NON_DEFAULT, None).selected_options(), NON_DEFAULT)

    def test_returns_new_options_and_leaves_the_input_alone(self):
        original = ConversionOptions()
        dialog = self._dialog(original, None)
        dialog.enable_plugins_cb.setChecked(True)
        dialog.docintel_endpoint_edit.setText("https://new.example")

        selected = dialog.selected_options()

        self.assertTrue(selected.enable_plugins)
        self.assertEqual(selected.docintel_endpoint, "https://new.example")
        self.assertEqual(original, ConversionOptions())

    def test_item_hints_apply_to_the_target_item(self):
        item = make_item()
        dialog = self._dialog(ConversionOptions(), item)
        self.assertEqual(dialog.extension_override_edit.text(), ".md")
        dialog.charset_override_edit.setText("latin-1")

        dialog.apply_item_overrides()

        self.assertEqual(item.charset_override, "latin-1")
        self.assertEqual(item.extension_override, ".md")

    def test_without_a_target_item_hints_are_disabled_and_ignored(self):
        dialog = self._dialog(ConversionOptions(), None)
        self.assertFalse(dialog.extension_override_edit.isEnabled())
        dialog.apply_item_overrides()

    def test_dialog_no_longer_knows_the_main_window(self):
        source = REPO_ROOT / "app" / "ui" / "advanced_settings_dialog.py"
        modules = {
            node.module
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("app.ui.main_window", modules)


class WindowOptionsTests(WindowTestCase):
    def test_window_holds_one_options_value(self):
        self.assertEqual(self.window.conversion_options, ConversionOptions())
        for field in dataclasses.fields(ConversionOptions):
            with self.subTest(field=field.name):
                self.assertFalse(hasattr(self.window, field.name))

    def _run_dialog(self, result):
        with mock.patch("app.ui.main_window.AdvancedSettingsDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = result
            dialog.selected_options.return_value = NON_DEFAULT
            self.window._show_advanced_settings()
        return dialog_class, dialog

    def test_accepting_the_dialog_replaces_options_and_applies_hints(self):
        self.add_sources("a.txt")
        selected = self.window.model.item_at(0)

        dialog_class, dialog = self._run_dialog(QDialog.DialogCode.Accepted)

        dialog_class.assert_called_once_with(ConversionOptions(), selected, self.window)
        dialog.apply_item_overrides.assert_called_once_with()
        self.assertIs(self.window.conversion_options, NON_DEFAULT)

    def test_cancelling_the_dialog_changes_nothing(self):
        _, dialog = self._run_dialog(QDialog.DialogCode.Rejected)

        dialog.apply_item_overrides.assert_not_called()
        self.assertEqual(self.window.conversion_options, ConversionOptions())

    def test_running_worker_keeps_the_options_it_started_with(self):
        before = self.window.conversion_options
        self.add_sources("a.txt")
        self.wait_started(1)

        self.window.conversion_options = NON_DEFAULT
        self.converter.release_all()
        settle()

        self.assertIs(self.converter.options_seen[0], before)

    def test_new_conversions_use_the_new_options(self):
        self.window.conversion_options = NON_DEFAULT
        self.add_sources("a.txt")
        self.wait_started(1)
        self.assertIs(self.converter.options_seen[0], NON_DEFAULT)


if __name__ == "__main__":
    unittest.main()
