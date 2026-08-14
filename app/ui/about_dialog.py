"""About dialog for MarkItDown Desktop."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from app.core.converter import get_markitdown_version
from app.i18n import tr


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(360)

        md_version = get_markitdown_version()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("about.heading")))
        layout.addWidget(QLabel(tr("about.markitdown_version", version=md_version)))
        layout.addWidget(QLabel(tr("about.description")))

        link = QLabel('<a href="https://github.com/microsoft/markitdown">github.com/microsoft/markitdown</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
