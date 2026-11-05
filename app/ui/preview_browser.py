"""The rendered preview of converted text."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser


class PreviewBrowser(QTextBrowser):
    """Shows converted text without reading anything that text points at.

    Converted text comes from other people's files and pages. Left alone, Qt
    opens whatever an image or stylesheet names, local files and network shares
    included. Only an image embedded in the text itself still shows. The blank
    image has to be a real one: for an empty answer Qt reads the file on its own.
    """

    def __init__(self):
        super().__init__()
        self._blank_image = QImage(1, 1, QImage.Format.Format_ARGB32)
        self._blank_image.fill(0)
        # By itself QTextBrowser loads relative and `file:` links into the view.
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_link_clicked)

    def loadResource(self, kind, name):
        if name.scheme() == "data":
            return super().loadResource(kind, name)
        return self._blank_image if kind == QTextDocument.ResourceType.ImageResource else ""

    def _anchor_for(self, fragment: str) -> str:
        """The anchor a link means: the exact one, or else one differing only in case."""
        folded = fragment.casefold()
        close_match = fragment
        block = self.document().begin()
        while block.isValid():
            piece = block.begin()
            while not piece.atEnd():
                for name in piece.fragment().charFormat().anchorNames():
                    if name == fragment:
                        return name
                    if close_match is fragment and name.casefold() == folded:
                        close_match = name
                piece += 1
            block = block.next()
        return close_match

    def _on_link_clicked(self, url: QUrl) -> None:
        """A link scrolls or leaves for a browser. Anything else does nothing."""
        if url.isRelative() and url.hasFragment() and not url.path() and not url.hasQuery():
            self.scrollToAnchor(self._anchor_for(url.fragment()))
        elif url.scheme() == "mailto" or (url.scheme() in ("http", "https") and url.host()):
            QDesktopServices.openUrl(url)
