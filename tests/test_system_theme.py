"""Follow system theme must read the system, never the palette the app replaced."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from qt_support import WindowTestCase, qapp


def hints(scheme) -> SimpleNamespace:
    return SimpleNamespace(colorScheme=lambda: scheme)


def system_says(scheme):
    return mock.patch.object(QGuiApplication, "styleHints", return_value=hints(scheme))


class DetectTests(unittest.TestCase):
    def setUp(self):
        qapp()

    def test_the_system_answer_wins_over_the_fallback(self):
        from app.ui.main_window import detect_system_theme

        with system_says(Qt.ColorScheme.Light):
            self.assertEqual(detect_system_theme(fallback="dark"), "light")
        with system_says(Qt.ColorScheme.Dark):
            self.assertEqual(detect_system_theme(fallback="light"), "dark")

    def test_an_unknown_answer_uses_the_fallback(self):
        from app.ui.main_window import detect_system_theme

        with system_says(Qt.ColorScheme.Unknown):
            self.assertEqual(detect_system_theme(fallback="dark"), "dark")
            self.assertEqual(detect_system_theme(fallback="light"), "light")

    def test_a_qt_without_color_scheme_uses_the_fallback(self):
        from app.ui.main_window import detect_system_theme

        # Qt before 6.5 has no colorScheme(), and requirements.txt does not pin Qt.
        with mock.patch.object(QGuiApplication, "styleHints", return_value=SimpleNamespace()):
            self.assertEqual(detect_system_theme(fallback="dark"), "dark")


class ThemeSwitchTests(WindowTestCase):
    def _theme(self) -> str:
        return qapp().property("themeName")

    def test_dark_then_system_returns_to_a_light_system(self):
        with system_says(Qt.ColorScheme.Light):
            self.window._set_theme_preference("dark")
            self.assertEqual(self._theme(), "dark")
            self.window._set_theme_preference("system")
            self.assertEqual(self._theme(), "light")

    def test_light_then_system_returns_to_a_dark_system(self):
        with system_says(Qt.ColorScheme.Dark):
            self.window._set_theme_preference("light")
            self.window._set_theme_preference("system")
            self.assertEqual(self._theme(), "dark")

    def test_an_unknown_system_uses_the_palette_from_before_the_app_replaced_it(self):
        self.window._launch_theme = "light"
        with system_says(Qt.ColorScheme.Unknown):
            self.window._set_theme_preference("dark")
            self.window._set_theme_preference("system")
            self.assertEqual(self._theme(), "light")

    def test_the_window_listens_to_the_system_changing_its_scheme(self):
        # The real signal on the real hints, taken before the patch replaces them.
        changed = QGuiApplication.styleHints().colorSchemeChanged
        self.window._set_theme_preference("system")
        with system_says(Qt.ColorScheme.Dark):
            changed.emit(Qt.ColorScheme.Dark)
            self.assertEqual(self._theme(), "dark")
        with system_says(Qt.ColorScheme.Light):
            changed.emit(Qt.ColorScheme.Light)
            self.assertEqual(self._theme(), "light")

    def test_a_live_system_change_applies_only_when_following_the_system(self):
        self.window._set_theme_preference("light")
        with system_says(Qt.ColorScheme.Dark):
            self.window._on_system_color_scheme_changed()
            self.assertEqual(self._theme(), "light")
            self.window._set_theme_preference("system")
            self.assertEqual(self._theme(), "dark")
        with system_says(Qt.ColorScheme.Light):
            self.window._on_system_color_scheme_changed()
            self.assertEqual(self._theme(), "light")


if __name__ == "__main__":
    unittest.main()
