"""Entry point for MarkItDown Desktop."""
from __future__ import annotations

import os
import sys


def _configure_qt_fonts() -> None:
    """PySide6 no longer ships fonts; point Qt at the OS font directory."""
    if "QT_QPA_FONTDIR" in os.environ:
        return
    if sys.platform.startswith("win"):
        candidate = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    elif sys.platform == "darwin":
        candidate = "/System/Library/Fonts"
    else:
        return
    if os.path.isdir(candidate):
        os.environ["QT_QPA_FONTDIR"] = candidate


_configure_qt_fonts()

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow

WINDOWS_APP_ID = "andrest04.MarkItDownDesktop"


def icon_path() -> str:
    """The icon sits next to this file, or in the bundle of a packaged build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "icon.png")


def app_icon() -> QIcon:
    return QIcon(icon_path())


def set_windows_app_id() -> None:
    """Without its own id, Windows groups the app under python.exe's taskbar icon."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass  # Only the taskbar grouping is lost; the window keeps its icon.


def main() -> int:
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setOrganizationName("andres")
    app.setApplicationName("MarkItDownDesktop")
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
