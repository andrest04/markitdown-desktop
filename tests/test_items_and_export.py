"""Item creation, path classification and Markdown export."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qt_support import WindowTestCase, settle

from app.core.queue_model import ItemStatus, QueueItem, QueueTableModel, SourceKind
from app.i18n import TRANSLATIONS, tr


def converted_item(name: str, text: str = "# text") -> QueueItem:
    return QueueItem(
        source=f"/somewhere/{name}",
        kind=SourceKind.FILE,
        display_name=name,
        status=ItemStatus.DONE,
        markdown_result=text,
    )


class ItemCreationTests(unittest.TestCase):
    def test_from_path_makes_the_path_absolute(self):
        item = QueueItem.from_path(os.path.join("some", "dir", "report.PDF"))
        self.assertEqual(item.source, os.path.abspath(os.path.join("some", "dir", "report.PDF")))
        self.assertIs(item.kind, SourceKind.FILE)
        self.assertEqual(item.display_name, "report.PDF")
        self.assertEqual(item.detected_type, "PDF")

    def test_from_path_without_an_extension_uses_the_generic_type_key(self):
        self.assertEqual(QueueItem.from_path("noext").detected_type, "type.file")

    def test_from_url(self):
        item = QueueItem.from_url("https://example.com/page")
        self.assertEqual(item.source, "https://example.com/page")
        self.assertIs(item.kind, SourceKind.URL)
        self.assertEqual(item.display_name, "https://example.com/page")
        self.assertEqual(item.detected_type, "type.webpage")

    def test_from_url_recognizes_youtube(self):
        self.assertEqual(QueueItem.from_url("https://youtu.be/abc").detected_type, "YouTube")

    def test_add_item_returns_the_row(self):
        model = QueueTableModel()
        self.assertEqual(model.add_item(converted_item("a.txt")), 0)
        self.assertEqual(model.add_item(converted_item("b.txt")), 1)


class ClassifyPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _touch(self, relative: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        return str(path)

    def test_files_keep_their_order_and_unsupported_ones_are_counted(self):
        from app.core.converter import classify_paths

        first = self._touch("b.pdf")
        second = self._touch("a.txt")
        result = classify_paths([first, self._touch("tool.exe"), second])

        self.assertEqual(result.files, [first, second])
        self.assertEqual(result.skipped, 1)
        self.assertFalse(result.saw_folder)

    def test_folders_are_walked_and_silently_filtered(self):
        from app.core.converter import classify_paths

        inside = self._touch("nested/deep/a.txt")
        self._touch("nested/tool.exe")
        result = classify_paths([str(self.root / "nested")])

        self.assertEqual(result.files, [inside])
        self.assertEqual(result.skipped, 0)
        self.assertTrue(result.saw_folder)

    def test_missing_paths_are_ignored(self):
        from app.core.converter import classify_paths

        result = classify_paths([str(self.root / "gone.txt")])
        self.assertEqual((result.files, result.skipped, result.saw_folder), ([], 0, False))


class ExportMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def _names(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir())

    def test_existing_files_are_never_overwritten(self):
        from app.core.converter import export_markdown

        (self.folder / "a.md").write_text("keep me", encoding="utf-8")

        result = export_markdown([converted_item("a.txt", "new")], self.folder)

        self.assertEqual((self.folder / "a.md").read_text(encoding="utf-8"), "keep me")
        self.assertEqual((self.folder / "a (1).md").read_text(encoding="utf-8"), "new")
        self.assertEqual(result.written, [self.folder / "a (1).md"])
        self.assertEqual(result.failures, [])

    def test_items_with_the_same_name_do_not_collide(self):
        from app.core.converter import export_markdown

        items = [
            QueueItem(source="/one/a.txt", kind=SourceKind.FILE, display_name="a.txt", markdown_result="one"),
            QueueItem(source="/two/a.pdf", kind=SourceKind.FILE, display_name="a.pdf", markdown_result="two"),
        ]
        export_markdown(items, self.folder)

        self.assertEqual(self._names(), ["a (1).md", "a.md"])
        self.assertEqual((self.folder / "a.md").read_text(encoding="utf-8"), "one")
        self.assertEqual((self.folder / "a (1).md").read_text(encoding="utf-8"), "two")

    def test_written_files_are_utf8(self):
        from app.core.converter import export_markdown

        export_markdown([converted_item("a.txt", "ñandú")], self.folder)
        self.assertEqual((self.folder / "a.md").read_bytes(), "ñandú".encode())

    def test_os_error_is_collected_not_raised_and_the_rest_continue(self):
        from app.core.converter import export_markdown

        bad, good = converted_item("bad.txt"), converted_item("good.txt")
        real_write_text = Path.write_text

        def flaky_write(path, *args, **kwargs):
            if path.name == "bad.md":
                raise OSError("disk full")
            return real_write_text(path, *args, **kwargs)

        with mock.patch("pathlib.Path.write_text", flaky_write):
            result = export_markdown([bad, good], self.folder)

        self.assertEqual(result.failures, [(bad, "disk full")])
        self.assertEqual(result.written, [self.folder / "good.md"])

    def test_unusable_folder_is_reported(self):
        from app.core.converter import export_markdown

        not_a_folder = self.folder / "file"
        not_a_folder.write_text("x", encoding="utf-8")

        result = export_markdown([converted_item("a.txt")], not_a_folder)

        self.assertEqual(result.written, [])
        self.assertEqual(len(result.failures), 1)


class WindowAddingTests(WindowTestCase):
    """Characterization of the add flows, which must survive the helper extraction."""

    def test_adding_starts_conversion_and_selects_the_first_row(self):
        self.add_sources("a.txt", "b.txt")
        self.assertEqual(len(self.window.model.items()), 2)
        self.assertEqual(self.window._selected_row(), 0)
        self.wait_started(2)
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.added_files", count=2))

    def test_existing_selection_is_kept(self):
        self.add_sources("a.txt", "b.txt")
        self.window.table_view.selectRow(1)
        self.add_sources("c.txt")
        self.assertEqual(self.window._selected_row(), 1)

    def test_duplicates_are_not_queued_twice(self):
        path = self.make_source("a.txt")
        self.window._add_paths([path, path])
        self.window._add_paths([path])
        self.assertEqual(len(self.window.model.items()), 1)

    def test_a_folder_and_a_file_inside_it_are_queued_once(self):
        path = self.make_source("a.txt")
        self.window._add_paths([str(self.sources), path])
        self.assertEqual(len(self.window.model.items()), 1)

    def test_skipped_files_are_mentioned(self):
        self.window._add_paths([self.make_source("a.txt"), self.make_source("tool.exe")])
        message = self.window.status_bar.currentMessage()
        self.assertIn(tr("status.added_files", count=1), message)
        self.assertIn(tr("status.skipped_unsupported", count=1), message)

    def test_only_unsupported_files_show_the_message_box(self):
        with mock.patch("app.ui.main_window.QMessageBox.information") as information:
            self.window._add_paths([self.make_source("tool.exe")])
        information.assert_called_once()
        self.assertEqual(self.window.model.items(), [])

    def test_empty_folder_shows_the_message_box(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with mock.patch("app.ui.main_window.QMessageBox.information") as information:
            self.window._add_paths([str(empty)])
        information.assert_called_once()

    def test_url_is_queued_and_the_field_cleared(self):
        self.window.url_edit.setText("  https://example.com/page ")
        self.window.action_add_url()
        self.assertEqual(self.window.url_edit.text(), "")
        self.assertEqual(self.window.model.item_at(0).source, "https://example.com/page")
        self.assertEqual(self.window._selected_row(), 0)
        self.wait_started(1)

    def test_invalid_url_warns(self):
        self.window.url_edit.setText("ftp://example.com")
        with mock.patch("app.ui.main_window.QMessageBox.warning") as warning:
            self.window.action_add_url()
        warning.assert_called_once()
        self.assertEqual(self.window.model.items(), [])

    def test_duplicate_url_is_reported_and_keeps_the_field(self):
        self.window.url_edit.setText("https://example.com")
        self.window.action_add_url()
        self.window.url_edit.setText("https://example.com")
        self.window.action_add_url()
        self.assertEqual(len(self.window.model.items()), 1)
        self.assertEqual(self.window.url_edit.text(), "https://example.com")
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.url_already_queued"))


class WindowExportTests(WindowTestCase):
    def _convert(self, *names: str) -> None:
        self.add_sources(*names)
        self.converter.release_all()
        settle()

    def _choose_folder(self, folder: Path):
        return mock.patch("app.ui.main_window.QFileDialog.getExistingDirectory", return_value=str(folder))

    def test_export_all_keeps_existing_files_and_reports_the_count(self):
        self._convert("a.txt")
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "a.md").write_text("keep me", encoding="utf-8")

        with self._choose_folder(folder):
            self.window.action_export_all()

        self.assertEqual((folder / "a.md").read_text(encoding="utf-8"), "keep me")
        self.assertTrue((folder / "a (1).md").exists())
        self.assertEqual(
            self.window.status_bar.currentMessage(),
            tr("status.exported", count=1, folder=str(folder)),
        )

    def test_export_failure_is_shown_to_the_user(self):
        self._convert("a.txt")
        not_a_folder = self.tmp / "file"
        not_a_folder.write_text("x", encoding="utf-8")

        with self._choose_folder(not_a_folder), mock.patch("app.ui.main_window.QMessageBox.warning") as warning:
            self.window.action_export_all()

        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], tr("msgbox.export_failed.title"))
        self.assertIn("a.txt", warning.call_args.args[2])

    def test_save_copy_failure_is_shown_to_the_user(self):
        self._convert("a.txt")
        self.window.table_view.selectRow(0)
        # Writing to a path that is a folder raises a real OSError.
        with (
            mock.patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(self.tmp), "")),
            mock.patch("app.ui.main_window.QMessageBox.warning") as warning,
        ):
            self.window.action_save_current()

        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], tr("msgbox.save_copy_failed.title"))

    def test_save_copy_writes_the_chosen_file(self):
        self._convert("a.txt")
        self.window.table_view.selectRow(0)
        target = self.tmp / "copy.md"
        with mock.patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            self.window.action_save_current()
        self.assertEqual(target.read_text(encoding="utf-8"), "# converted a.txt")

    def test_new_strings_exist_in_every_language(self):
        keys = (
            "msgbox.export_failed.title",
            "msgbox.export_failed.text",
            "msgbox.save_copy_failed.title",
            "msgbox.save_copy_failed.text",
        )
        for key in keys:
            for language, table in TRANSLATIONS.items():
                with self.subTest(key=key, language=language):
                    self.assertIn(key, table)


if __name__ == "__main__":
    unittest.main()
