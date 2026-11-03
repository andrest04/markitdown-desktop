"""The app icon: its files, the window icon at run time, and the packaged builds."""
from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSize
from qt_support import qapp

# Importing main points Qt at the OS fonts; keep that out of the other tests.
with mock.patch.dict(os.environ):
    import main

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


class IconFileTests(unittest.TestCase):
    def test_windows_icon_holds_every_size_shortcuts_ask_for(self):
        data = (ASSETS / "icon.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        widths = {data[6 + 16 * i] or 256 for i in range(count)}
        self.assertLessEqual({16, 24, 32, 48, 256}, widths)

    def test_macos_icon_is_an_icns_file(self):
        self.assertEqual((ASSETS / "icon.icns").read_bytes()[:4], b"icns")


class WindowIconTests(unittest.TestCase):
    def setUp(self):
        self.app = qapp()

    def test_the_icon_loads_from_the_source_tree(self):
        icon = main.app_icon()
        self.assertFalse(icon.isNull())
        self.assertGreaterEqual(icon.actualSize(QSize(256, 256)).width(), 256)

    def test_the_icon_is_found_in_a_packaged_build(self):
        with mock.patch.object(main.sys, "_MEIPASS", "/bundle", create=True):
            self.assertEqual(Path(main.icon_path()), Path("/bundle/assets/icon.png"))

    def test_the_windows_taskbar_id_is_set_only_on_windows(self):
        fake_ctypes = mock.Mock()
        with mock.patch.dict("sys.modules", {"ctypes": fake_ctypes}):
            with mock.patch.object(main.sys, "platform", "linux"):
                main.set_windows_app_id()
            fake_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()

            with mock.patch.object(main.sys, "platform", "win32"):
                main.set_windows_app_id()
            fake_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(main.WINDOWS_APP_ID)

    def test_a_failed_taskbar_id_does_not_stop_the_app(self):
        fake_ctypes = mock.Mock()
        fake_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.side_effect = OSError("denied")
        with mock.patch.dict("sys.modules", {"ctypes": fake_ctypes}), mock.patch.object(main.sys, "platform", "win32"):
            main.set_windows_app_id()


class PackagingTests(unittest.TestCase):
    def test_both_release_builds_use_the_icon_and_bundle_it(self):
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertEqual(release.count("--add-data assets/icon.png:assets"), 2)
        self.assertEqual(release.count("assets/icon.ico"), 2)
        self.assertEqual(release.count("assets/icon.icns"), 2)

    def test_the_installer_uses_the_icon(self):
        script = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn(r"SetupIconFile=assets\icon.ico", script)


if __name__ == "__main__":
    unittest.main()
