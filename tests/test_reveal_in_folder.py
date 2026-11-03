"""Show in folder hands the path to the OS literally, with no shell to expand it."""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest import mock

from qt_support import WindowTestCase

from app.i18n import tr
from app.ui.main_window import reveal_command

AWKWARD_NAMES = [
    "plain.md",
    "with space.md",
    "%TEMP% and %PATH%.md",
    "this & that.md",
    "a^b;c(d)'e.md",
    "informe año ñandú 日本語.md",
]


def on_platform(name: str):
    return mock.patch("sys.platform", name)


@contextmanager
def system_root(value: str | None):
    """Set or remove SystemRoot for the block. Only the builder runs, never Explorer."""
    with mock.patch.dict(os.environ):
        os.environ.pop("SystemRoot", None)
        if value is not None:
            os.environ["SystemRoot"] = value
        yield


class RevealCommandTests(unittest.TestCase):
    def _command(self, path: str):
        return reveal_command(path)

    def test_windows_quotes_the_path_for_explorer_and_changes_nothing_in_it(self):
        for name in AWKWARD_NAMES:
            path = "C:\\Users\\some one\\Downloads\\" + name
            with self.subTest(name=name), on_platform("win32"), system_root("C:\\Windows"):
                self.assertEqual(self._command(path), f'C:\\Windows\\explorer.exe /select,"{path}"')

    def test_windows_never_leaves_finding_explorer_to_the_search_order(self):
        # CreateProcess looks in the current folder first for a bare name.
        with on_platform("win32"), system_root("D:\\WinNT"):
            self.assertEqual(self._command("C:\\a.md"), 'D:\\WinNT\\explorer.exe /select,"C:\\a.md"')

    def test_windows_without_a_system_root_falls_back_to_the_bare_name(self):
        for root in (None, ""):
            with self.subTest(root=root), on_platform("win32"), system_root(root):
                self.assertEqual(self._command("C:\\a.md"), 'explorer /select,"C:\\a.md"')

    def test_macos_reveals_the_file(self):
        for name in AWKWARD_NAMES:
            path = "/Users/some one/Downloads/" + name
            with self.subTest(name=name), on_platform("darwin"):
                self.assertEqual(self._command(path), ["open", "-R", path])

    def test_linux_opens_the_folder(self):
        for name in AWKWARD_NAMES:
            path = "/home/some one/Downloads/" + name
            with self.subTest(name=name), on_platform("linux"):
                self.assertEqual(self._command(path), ["xdg-open", "/home/some one/Downloads"])


class RevealWiringTests(WindowTestCase):
    def _reveal(self, platform: str, name: str = "%TEMP% & more.md"):
        path = self.tmp / name
        path.write_text("x", encoding="utf-8")
        with on_platform(platform), mock.patch("app.ui.main_window.subprocess.Popen") as popen:
            self.window._open_containing_folder(str(path))
        popen.assert_called_once()
        return os.path.normpath(path), popen.call_args

    def test_no_platform_uses_a_shell(self):
        for platform in ("win32", "darwin", "linux"):
            with self.subTest(platform=platform):
                _, call = self._reveal(platform)
                self.assertFalse(call.kwargs.get("shell", False))

    def test_the_built_command_is_what_runs(self):
        for platform in ("win32", "darwin", "linux"):
            with self.subTest(platform=platform):
                path, call = self._reveal(platform)
                with on_platform(platform):
                    self.assertEqual(call.args[0], reveal_command(path))

    def test_a_missing_file_runs_nothing_and_says_so(self):
        with mock.patch("app.ui.main_window.subprocess.Popen") as popen:
            self.window._open_containing_folder(str(self.tmp / "gone.md"))
        popen.assert_not_called()
        self.assertEqual(self.window.status_bar.currentMessage(), tr("status.file_missing"))

    def test_the_os_refusing_does_not_raise(self):
        path = self.tmp / "a.md"
        path.write_text("x", encoding="utf-8")
        with mock.patch("app.ui.main_window.subprocess.Popen", side_effect=OSError("no such program")):
            self.window._open_containing_folder(str(path))


if __name__ == "__main__":
    unittest.main()
