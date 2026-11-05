"""Adding what is already in the list says so, in the manner of a repeated link."""
from __future__ import annotations

from unittest import mock

from qt_support import WindowTestCase, settle

from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager


class AlreadyQueuedTests(WindowTestCase):
    def add(self, *paths: str):
        with mock.patch("app.ui.main_window.QMessageBox.information") as information:
            self.window._add_paths(list(paths))
        return information

    def message(self) -> str:
        return self.window.status_bar.currentMessage()

    def test_one_file_already_queued(self):
        path = self.make_source("a.txt")
        self.add(path)

        information = self.add(path)

        information.assert_not_called()
        self.assertEqual(self.message(), tr("status.file_already_queued"))
        self.assertEqual(len(self.window.model.items()), 1)

    def test_a_folder_already_queued_is_not_called_unsupported(self):
        self.make_source("a.txt")
        self.make_source("b.txt")
        self.add(str(self.sources))

        information = self.add(str(self.sources))

        information.assert_not_called()
        self.assertEqual(self.message(), tr("status.files_already_queued", count=2))
        self.assertEqual(len(self.window.model.items()), 2)

    def test_a_folder_with_one_file_reads_as_one(self):
        self.make_source("a.txt")
        self.add(str(self.sources))
        self.add(str(self.sources))
        self.assertEqual(self.message(), tr("status.file_already_queued"))

    def test_the_message_retranslates_for_the_next_time(self):
        path = self.make_source("a.txt")
        self.add(path)
        i18n_manager._language = LANG_ES
        self.add(path)
        self.assertEqual(self.message(), "Ese archivo ya está en la lista")

    def test_duplicates_and_unsupported_files_mention_both_and_ask_nothing(self):
        path = self.make_source("a.txt")
        self.add(path)

        information = self.add(path, self.make_source("tool.exe"))

        information.assert_not_called()
        self.assertIn(tr("status.file_already_queued"), self.message())
        self.assertIn(tr("status.skipped_unsupported", count=1), self.message())

    def test_new_and_duplicate_files_start_the_new_ones_and_mention_the_rest(self):
        first = self.make_source("a.txt")
        second = self.make_source("b.txt")
        self.add(first, second)

        information = self.add(first, second, self.make_source("c.txt"))

        information.assert_not_called()
        self.assertEqual(len(self.window.model.items()), 3)
        self.assertIn(tr("status.added_files", count=1), self.message())
        self.assertIn(tr("status.some_already_queued", count=2), self.message())

    def test_new_duplicate_and_unsupported_mention_all_three(self):
        first = self.make_source("a.txt")
        self.add(first)

        self.add(first, self.make_source("b.txt"), self.make_source("tool.exe"))

        for part in (
            tr("status.added_files", count=1),
            tr("status.some_already_queued", count=1),
            tr("status.skipped_unsupported", count=1),
        ):
            self.assertIn(part, self.message())

    def test_the_same_new_path_twice_in_one_selection_is_not_a_duplicate(self):
        path = self.make_source("a.txt")
        self.add(path, path)
        self.assertEqual(self.message(), tr("status.added_files", count=1))

    def test_a_folder_and_a_file_inside_it_is_not_a_duplicate_either(self):
        path = self.make_source("a.txt")
        self.add(str(self.sources), path)
        self.assertEqual(self.message(), tr("status.added_files", count=1))

    def test_a_finished_item_counts_as_in_the_list(self):
        path = self.make_source("a.txt")
        self.add(path)
        self.converter.release_all()
        settle()
        self.add(path)
        self.assertEqual(self.message(), tr("status.file_already_queued"))

    def test_nothing_starts_again(self):
        path = self.make_source("a.txt")
        self.add(path)
        self.converter.release_all()
        settle()
        self.add(path)
        settle()
        self.assertEqual(self.converter.call_count("a.txt"), 1)
        self.assertEqual(self.downloaded_names(), ["a.md"])


class StillUnsupportedTests(WindowTestCase):
    def add(self, *paths: str):
        with mock.patch("app.ui.main_window.QMessageBox.information") as information:
            self.window._add_paths(list(paths))
        return information

    def test_an_unsupported_selection_keeps_its_dialog(self):
        self.add(self.make_source("a.txt"))
        self.add(self.make_source("tool.exe")).assert_called_once()

    def test_an_empty_folder_keeps_its_dialog_with_items_in_the_list(self):
        self.add(self.make_source("a.txt"))
        empty = self.tmp / "empty"
        empty.mkdir()
        self.add(str(empty)).assert_called_once()

    def test_a_folder_of_unsupported_files_keeps_its_dialog(self):
        folder = self.tmp / "tools"
        folder.mkdir()
        (folder / "tool.exe").write_text("x", encoding="utf-8")
        self.add(str(folder)).assert_called_once()
