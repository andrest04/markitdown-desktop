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

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("andres")
    app.setApplicationName("MarkItDownDesktop")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
