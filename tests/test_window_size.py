"""The window opens small for the empty screen and grows when there is work to show."""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QRect, QSize, Qt
from qt_support import FakeSettings, WindowTestCase, process_events, settle

from app.ui.main_window import COMPACT_WINDOW_SIZE, WORKING_WINDOW_SIZE, MainWindow

DESKTOP = QRect(0, 0, 1920, 1040)
SMALL_LAPTOP = QRect(0, 0, 1000, 700)


class WindowSizeTestCase(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.window._available_area = lambda: DESKTOP

    def assert_size(self, expected: tuple[int, int]) -> None:
        process_events()
        self.assertEqual(self.window.size(), QSize(*expected))

    def clear(self) -> None:
        self.window.action_clear_all()
        process_events()


class CompactEmptyScreenTests(WindowSizeTestCase):
    def test_it_opens_at_the_compact_size(self):
        self.assert_size(COMPACT_WINDOW_SIZE)

    def test_the_empty_screen_fits_the_compact_size_in_both_languages(self):
        for lang_button in (self.window.lang_es_btn, self.window.lang_en_btn):
            lang_button.click()
            process_events()
            hint = self.window.centralWidget().minimumSizeHint()
            self.assertLessEqual(hint.width(), COMPACT_WINDOW_SIZE[0])
            self.assertLessEqual(hint.height(), COMPACT_WINDOW_SIZE[1])

    def test_a_big_saved_window_still_opens_compact(self):
        saved = FakeSettings()
        previous = MainWindow()
        self.addCleanup(previous.deleteLater)
        previous.settings = saved
        previous.resize(1500, 1000)
        previous.close()
        with mock.patch("app.ui.main_window.QSettings", lambda *args: saved):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.size(), QSize(*COMPACT_WINDOW_SIZE))

    def test_a_maximized_saved_window_still_opens_compact(self):
        saved = FakeSettings()
        previous = MainWindow()
        self.addCleanup(previous.deleteLater)
        previous.settings = saved
        previous.showMaximized()
        process_events()
        previous.close()
        with mock.patch("app.ui.main_window.QSettings", lambda *args: saved):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.assertFalse(window.isMaximized())
        self.assertEqual(window.size(), QSize(*COMPACT_WINDOW_SIZE))


class GrowingTests(WindowSizeTestCase):
    def test_the_first_file_grows_the_window(self):
        self.add_sources("a.txt")
        self.assert_size(WORKING_WINDOW_SIZE)

    def test_later_files_leave_a_resized_window_alone(self):
        self.add_sources("a.txt")
        self.window.resize(1000, 700)
        self.add_sources("b.txt")
        self.assert_size((1000, 700))

    def test_clearing_the_list_goes_back_to_compact(self):
        self.add_sources("a.txt")
        self.clear()
        self.assert_size(COMPACT_WINDOW_SIZE)

    def test_a_size_the_person_chose_comes_back_with_the_next_file(self):
        self.add_sources("a.txt")
        self.window.resize(1000, 700)
        self.clear()
        self.add_sources("b.txt")
        self.assert_size((1000, 700))

    def test_the_chosen_size_survives_a_restart(self):
        saved = FakeSettings()
        self.window.settings = saved
        self.add_sources("a.txt")
        self.window.resize(1000, 700)
        # Closing with work in flight would ask first.
        self.converter.release_all()
        settle()
        self.window.close()
        with mock.patch("app.ui.main_window.QSettings", lambda *args: saved):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        window._available_area = lambda: DESKTOP
        window._apply_window_size(empty=False)
        self.assertEqual(window.size(), QSize(1000, 700))

    def test_a_small_screen_caps_the_growth_and_keeps_it_on_screen(self):
        self.window._available_area = lambda: SMALL_LAPTOP
        self.window.move(400, 300)
        self.add_sources("a.txt")
        process_events()
        frame = self.window.frameGeometry()
        self.assertTrue(SMALL_LAPTOP.contains(frame), frame)

    def test_a_maximized_window_is_left_alone(self):
        self.add_sources("a.txt")
        self.window.setWindowState(Qt.WindowState.WindowMaximized)
        process_events()
        with mock.patch.object(self.window, "resize") as resize:
            self.clear()
            self.add_sources("b.txt")
        resize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
