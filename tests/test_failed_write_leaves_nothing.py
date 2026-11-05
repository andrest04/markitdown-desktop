"""A write that fails leaves no new file, and never removes one that was there."""
from __future__ import annotations

import errno
import os
from pathlib import Path
from unittest import mock

from qt_support import WindowTestCase, pump_until

from app.core.converter import auto_save_markdown, export_markdown, save_copy
from app.core.queue_model import DisplayState, QueueItem, SourceKind

NO_ROOM = OSError(errno.ENOSPC, "No space left on device")
REAL_WRITE_TEXT = Path.write_text


def creates_the_file_then_fails(path, *_args, **_kwargs):
    """What a full disk does: the name goes in, the bytes do not."""
    REAL_WRITE_TEXT(path, "", encoding="utf-8")
    raise NO_ROOM


def disk_full():
    return mock.patch("pathlib.Path.write_text", creates_the_file_then_fails)


def make_item(name: str = "a.txt", text: str = "# text") -> QueueItem:
    return QueueItem(source=f"/somewhere/{name}", kind=SourceKind.FILE, display_name=name, markdown_result=text)


class AutoSaveTests(WindowTestCase):
    def failed_save(self):
        source = self.make_source("a.txt")
        with disk_full():
            self.window._add_paths([source])
            self.converter.release("a.txt")
            item = self.item_named("a.txt")
            self.assertTrue(pump_until(lambda: item.display_state == DisplayState.SAVE_FAILED))
        return item

    def test_a_failed_save_leaves_no_file(self):
        self.failed_save()
        self.assertEqual(self.downloaded_names(), [])

    def test_every_retry_on_a_full_disk_leaves_nothing_and_success_takes_the_first_name(self):
        item = self.failed_save()
        with disk_full():
            for _ in range(3):
                self.window._start_conversion([0])
                self.assertEqual(self.downloaded_names(), [])
        self.window._start_conversion([0])
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertEqual(item.display_state, DisplayState.SAVED)

    def test_the_failure_still_reaches_the_caller_with_its_errno(self):
        self.downloads.mkdir()
        with disk_full(), self.assertRaises(OSError) as caught:
            auto_save_markdown(make_item(), "# text", self.downloads)
        self.assertEqual(caught.exception.errno, errno.ENOSPC)

    def test_an_earlier_file_with_that_name_stays(self):
        self.downloads.mkdir()
        (self.downloads / "a.md").write_text("keep me", encoding="utf-8")
        with disk_full(), self.assertRaises(OSError):
            auto_save_markdown(make_item(), "# text", self.downloads)
        self.assertEqual(self.downloaded_names(), ["a.md"])
        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), "keep me")

    def test_a_name_taken_after_the_check_is_not_written_over_or_removed(self):
        self.downloads.mkdir()

        def another_program_got_there_first(directory, base_name):
            taken = directory / f"{base_name}.md"
            taken.write_text("theirs", encoding="utf-8")
            return taken

        with (
            mock.patch("app.core.converter.unique_download_path", another_program_got_there_first),
            self.assertRaises(OSError),
        ):
            auto_save_markdown(make_item(), "# text", self.downloads)
        self.assertEqual((self.downloads / "a.md").read_text(encoding="utf-8"), "theirs")


class ExportTests(WindowTestCase):
    def test_a_failed_export_leaves_no_file(self):
        folder = self.tmp / "out"
        folder.mkdir()
        with disk_full():
            result = export_markdown([make_item("a.txt"), make_item("b.txt")], folder)
        self.assertEqual(len(result.failures), 2)
        self.assertEqual(os.listdir(folder), [])

    def test_an_export_keeps_what_was_already_there(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "a.md").write_text("keep me", encoding="utf-8")
        with disk_full():
            export_markdown([make_item("a.txt")], folder)
        self.assertEqual(os.listdir(folder), ["a.md"])
        self.assertEqual((folder / "a.md").read_text(encoding="utf-8"), "keep me")


class _FullDiskFile:
    """A real open file whose writes fail, as they do once the disk fills."""

    def __init__(self, real):
        self._real = real

    def write(self, _text):
        raise NO_ROOM

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._real.close()
        return False


class SaveCopyTests(WindowTestCase):
    def full_disk_open(self):
        real_open = open
        return mock.patch("builtins.open", lambda *args, **kwargs: _FullDiskFile(real_open(*args, **kwargs)))

    def test_writes_the_text(self):
        target = self.tmp / "copy.md"
        save_copy(target, "# text")
        self.assertEqual(target.read_text(encoding="utf-8"), "# text")

    def test_replaces_a_file_the_person_chose_to_replace(self):
        target = self.tmp / "copy.md"
        target.write_text("old", encoding="utf-8")
        save_copy(target, "# text")
        self.assertEqual(target.read_text(encoding="utf-8"), "# text")

    def test_a_failed_new_file_is_removed(self):
        target = self.tmp / "copy.md"
        with self.full_disk_open(), self.assertRaises(OSError):
            save_copy(target, "# text")
        self.assertFalse(target.exists())

    def test_a_file_that_existed_is_never_removed(self):
        target = self.tmp / "copy.md"
        target.write_text("old", encoding="utf-8")
        with self.full_disk_open(), self.assertRaises(OSError):
            save_copy(target, "# text")
        self.assertTrue(target.exists())
