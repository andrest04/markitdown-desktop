"""MarkItDown wrapper and background conversion workers.

Wires the GUI to the real markitdown 0.1.6 API as found in
markitdown/_markitdown.py, markitdown/_stream_info.py and
markitdown/converters/_doc_intel_converter.py / _cu_converter.py:

    MarkItDown(
        *,
        enable_builtins: bool | None = None,
        enable_plugins: bool | None = None,
        docintel_endpoint: str | None = ...,
        docintel_credential: ... | None = ...,
        docintel_file_types: list | None = ...,
        docintel_api_version: str | None = ...,
        cu_endpoint: str | None = ...,
        cu_credential: ... | None = ...,
        cu_analyzer_id: str | None = ...,
        cu_file_types: list | None = ...,
        requests_session: requests.Session | None = ...,
    )

    MarkItDown.convert(source, *, stream_info: StreamInfo | None = None, **kwargs)
    MarkItDown.convert_local(path, *, stream_info=None, file_extension=None, url=None, **kwargs)
    MarkItDown.convert_uri(uri, *, stream_info=None, file_extension=None, mock_url=None, **kwargs)

    StreamInfo(mimetype=None, extension=None, charset=None, filename=None,
               local_path=None, url=None)

`keep_data_uris` is a keyword accepted by convert()/convert_local() and is
forwarded down to the markdownify-based converters (see
markitdown/converters/_markdownify.py).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from markitdown import MarkItDown, StreamInfo
from PySide6.QtCore import QObject, QRunnable, Signal

from app.core.queue_model import QueueItem, SourceKind

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize a URL/string into a safe base filename (no extension)."""
    name = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip(" .")
    return name[:150] if name else "untitled"


def url_to_basename(url: str) -> str:
    """Derive a filesystem-safe basename from a URL (strip scheme/query)."""
    parsed = urlparse(url)
    candidate = (parsed.netloc + parsed.path).strip("/")
    candidate = candidate.replace("/", "_")
    if not candidate:
        candidate = parsed.netloc or "webpage"
    return sanitize_filename(candidate)


def default_basename(item: QueueItem) -> str:
    """The base filename (no extension) an item's markdown result should use."""
    if item.kind == SourceKind.URL:
        return url_to_basename(item.source)
    return os.path.splitext(os.path.basename(item.source))[0]


def get_downloads_dir() -> Path:
    """Resolve the current user's Downloads folder.

    Uses Path.home() so this works for any account on Windows, macOS, or
    Linux, not just the machine this was developed on (never hardcode a
    specific user's path).
    """
    return Path.home() / "Downloads"


def unique_download_path(directory: Path, base_name: str) -> Path:
    """Return a non-colliding '<directory>/<base_name>.md' path.

    If that name already exists, numeric suffixes are appended --
    'name (1).md', 'name (2).md', etc. -- so an existing file is never
    silently overwritten.
    """
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{base_name}.md"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{base_name} ({counter}).md"
        counter += 1
    return candidate


def auto_save_markdown(item: QueueItem, markdown_text: str, downloads_dir: Path | None = None) -> Path:
    """Write `markdown_text` to the Downloads folder using a name derived from
    the item's source, avoiding collisions. Returns the path written to."""
    directory = downloads_dir if downloads_dir is not None else get_downloads_dir()
    base_name = sanitize_filename(default_basename(item))
    path = unique_download_path(directory, base_name)
    path.write_text(markdown_text, encoding="utf-8")
    return path

# Extensions markitdown's built-in converters recognize (used to filter
# recursive folder scans). PlainTextConverter/HtmlConverter also catch many
# text/* and application/*+xml mimetypes generically, but for a folder scan
# we only want to pick up files we have reasonable confidence about.
SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".html", ".htm", ".xml", ".rss", ".atom",
    ".docx", ".xlsx", ".xls", ".pptx", ".pdf", ".csv", ".json", ".ipynb",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".mp3", ".wav", ".m4a", ".msg", ".zip", ".epub",
}


@dataclass
class ConversionOptions:
    """Options mirrored from the Options panel, mapped to real MarkItDown kwargs."""

    enable_plugins: bool = False
    keep_data_uris: bool = False

    docintel_enabled: bool = False
    docintel_endpoint: str = ""

    cu_enabled: bool = False
    cu_endpoint: str = ""
    cu_analyzer_id: str = ""

    def build_markitdown(self) -> MarkItDown:
        kwargs: dict = {"enable_plugins": self.enable_plugins}
        if self.docintel_enabled and self.docintel_endpoint.strip():
            kwargs["docintel_endpoint"] = self.docintel_endpoint.strip()
        if self.cu_enabled and self.cu_endpoint.strip():
            kwargs["cu_endpoint"] = self.cu_endpoint.strip()
            if self.cu_analyzer_id.strip():
                kwargs["cu_analyzer_id"] = self.cu_analyzer_id.strip()
        return MarkItDown(**kwargs)


def convert_item(item: QueueItem, options: ConversionOptions) -> str:
    """Run an actual MarkItDown conversion for a single queue item.

    Kept independent of Qt so it can be exercised directly (e.g. in tests
    or a smoke-test script) without a QApplication/thread pool.
    """
    md = options.build_markitdown()

    stream_info_kwargs = {}
    if item.extension_override.strip():
        ext = item.extension_override.strip()
        stream_info_kwargs["extension"] = ext if ext.startswith(".") else f".{ext}"
    if item.mimetype_override.strip():
        stream_info_kwargs["mimetype"] = item.mimetype_override.strip()
    if item.charset_override.strip():
        stream_info_kwargs["charset"] = item.charset_override.strip()

    stream_info = StreamInfo(**stream_info_kwargs) if stream_info_kwargs else None

    convert_kwargs = {}
    if options.keep_data_uris:
        convert_kwargs["keep_data_uris"] = True

    if item.kind == SourceKind.URL:
        result = md.convert_uri(item.source, stream_info=stream_info, **convert_kwargs)
    else:
        result = md.convert_local(item.source, stream_info=stream_info, **convert_kwargs)

    return result.text_content


def detect_type_label(source: str, kind: SourceKind) -> str:
    """Best-effort, cheap type label for the queue table (no conversion)."""
    if kind == SourceKind.URL:
        lowered = source.lower()
        if "youtube.com" in lowered or "youtu.be" in lowered:
            return "YouTube"
        return "type.webpage"
    ext = os.path.splitext(source)[1].lower()
    return ext.lstrip(".").upper() if ext else "type.file"


def iter_supported_files(folder: str):
    """Recursively yield file paths under `folder` matching SUPPORTED_EXTENSIONS."""
    for root, _dirs, files in os.walk(folder):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                yield os.path.join(root, name)


class WorkerSignals(QObject):
    """Signals for ConversionWorker; QRunnable itself cannot emit signals."""

    started = Signal(int)
    finished = Signal(int, str)
    failed = Signal(int, str)


class ConversionWorker(QRunnable):
    """Runs a single item's conversion on a QThreadPool worker thread.

    Only ever touches widgets through the emitted signals (started/finished/
    failed), which the GUI connects with Qt.QueuedConnection semantics
    (the default for cross-thread signal/slot connections).
    """

    def __init__(self, row: int, item: QueueItem, options: ConversionOptions):
        super().__init__()
        self.row = row
        self.item = item
        self.options = options
        self.signals = WorkerSignals()

    def run(self) -> None:
        self.signals.started.emit(self.row)
        try:
            markdown_text = convert_item(self.item, self.options)
        except Exception as exc:  # noqa: BLE001 - must catch everything per-item
            self.signals.failed.emit(self.row, str(exc))
        else:
            self.signals.finished.emit(self.row, markdown_text)
