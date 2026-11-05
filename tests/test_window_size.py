"""The window opens small for the empty screen and grows when there is work to show."""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QRect, QSize, Qt
from qt_support import FakeSettings, WindowTestCase, process_events, settle

from app.ui.main_window import COMPACT_WINDOW_SIZE, WORKING_WINDOW_SIZE, MainWindow

DESKTOP = QRect(0, 0, 1920, 1040)
SMALL_LAPTOP = QRect(0, 0, 1000, 700)
# restoreGeometry() keeps a window on the real screen, whatever _available_area says.
OFFSCREEN_SCREEN = QRect(0, 0, 800, 800)


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


class PositionAcrossLaunchesTests(WindowSizeTestCase):
    """A shown window has a frame, and the position it saves is read back before it has one."""

    def launch(self, saved: FakeSettings, area: QRect = OFFSCREEN_SCREEN) -> MainWindow:
        with (
            mock.patch("app.ui.main_window.QSettings", lambda *args: saved),
            mock.patch.object(MainWindow, "_available_area", lambda window: area),
        ):
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            window.show()
            process_events()
        return window

    def test_the_offscreen_platform_gives_windows_a_frame(self):
        window = self.launch(FakeSettings())
        self.assertGreater(window.geometry().top(), window.frameGeometry().top())
        window.close()

    def test_a_position_stays_put_with_nothing_moved(self):
        saved = FakeSettings()
        window = self.launch(saved)
        window.move(20, 200)
        process_events()
        moved_to = window.pos()
        window.close()
        for _launch in range(3):
            window = self.launch(saved)
            self.assertEqual(window.pos(), moved_to)
            self.assertEqual(window.size(), QSize(*COMPACT_WINDOW_SIZE))
            window.close()

    def test_a_window_closed_maximized_comes_back_where_it_was(self):
        saved = FakeSettings()
        window = self.launch(saved)
        window.move(20, 200)
        process_events()
        moved_to = window.pos()
        window.showMaximized()
        process_events()
        window.close()
        for _launch in range(2):
            window = self.launch(saved)
            self.assertFalse(window.isMaximized())
            self.assertEqual(window.pos(), moved_to)
            window.close()

    def test_a_position_low_on_the_screen_comes_back_above_the_bottom_edge(self):
        area = QRect(0, 0, 800, 600)
        saved = FakeSettings()
        window = self.launch(saved)
        window.move(20, 280)
        process_events()
        window.close()
        positions = []
        for _launch in range(3):
            window = self.launch(saved, area)
            self.assertLessEqual(window.geometry().bottom(), area.bottom())
            positions.append(window.pos())
            window.close()
        self.assertEqual(positions[1:], positions[:-1])

    def test_a_first_launch_opens_with_its_frame_on_screen(self):
        window = self.launch(FakeSettings())
        self.assertEqual(window.frameGeometry().topLeft(), OFFSCREEN_SCREEN.topLeft())
        window.close()


if __name__ == "__main__":
    unittest.main()
