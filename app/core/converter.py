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
import threading
import warnings
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from urllib.parse import urlparse

# pydub (pulled in by markitdown audio converters) warns on import when
# ffmpeg is missing. Audio transcription is optional; surface real failures
# at conversion time instead of scaring every startup.
warnings.filterwarnings(
    "ignore",
    message=r"Couldn't find ffmpeg or avconv",
    category=RuntimeWarning,
    module=r"pydub\.utils",
)

from markitdown import MarkItDown, StreamInfo
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from app.core.queue_model import QueueItem, SourceKind

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize a URL/string into a safe base filename (no extension)."""
    name = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip(" .")
    return name[:150] if name else "untitled"


def get_markitdown_version() -> str:
    """Best-effort markitdown package version for display (About dialog)."""
    try:
        return pkg_version("markitdown")
    except PackageNotFoundError:
        from markitdown import __about__
        return getattr(__about__, "__version__", "unknown")


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


@dataclass
class ExportResult:
    """What `export_markdown` wrote, and which items failed with which error."""

    written: list[Path] = field(default_factory=list)
    failures: list[tuple[QueueItem, str]] = field(default_factory=list)


def export_markdown(items: list[QueueItem], folder: str | Path) -> ExportResult:
    """Write each item's markdown into `folder`, never overwriting a file.

    A failed item is recorded in the result and the rest still run, so
    OSError never reaches the caller.
    """
    directory = Path(folder)
    result = ExportResult()
    for item in items:
        try:
            path = unique_download_path(directory, sanitize_filename(default_basename(item)))
            path.write_text(item.markdown_result or "", encoding="utf-8")
        except OSError as exc:
            result.failures.append((item, str(exc)))
        else:
            result.written.append(path)
    return result


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


def is_supported_file(path: str) -> bool:
    """True when `path` has an extension markitdown can reasonably convert."""
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS


def supported_name_filter(label: str) -> str:
    """Qt file-dialog filter that lists only compatible extensions."""
    patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
    return f"{label} ({patterns})"


@dataclass(frozen=True)
class ConversionOptions:
    """Conversion settings, mapped to real MarkItDown kwargs.

    Frozen: workers on other threads hold the same instance, so a settings
    change replaces it (see `dataclasses.replace`) instead of mutating it.
    """

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


def iter_supported_files(folder: str):
    """Recursively yield file paths under `folder` matching SUPPORTED_EXTENSIONS."""
    for root, _dirs, files in os.walk(folder):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                yield os.path.join(root, name)


@dataclass(frozen=True)
class ClassifiedPaths:
    """Dropped or browsed paths, sorted out for queueing."""

    files: list[str]
    skipped: int  # explicitly given files with an unsupported extension
    saw_folder: bool


def classify_paths(paths: list[str]) -> ClassifiedPaths:
    """Expand folders and filter by extension, keeping the given order.

    Unsupported files inside a folder are not counted as skipped; only files
    the user pointed at directly are. Paths that do not exist are ignored.
    """
    files: list[str] = []
    skipped = 0
    saw_folder = False
    for path in paths:
        if os.path.isdir(path):
            saw_folder = True
            files.extend(iter_supported_files(path))
        elif os.path.isfile(path):
            if is_supported_file(path):
                files.append(path)
            else:
                skipped += 1
    return ClassifiedPaths(files, skipped, saw_folder)


class WorkerSignals(QObject):
    """Signals for ConversionWorker; QRunnable itself cannot emit signals."""

    # Payload is the QueueItem itself: rows shift when the queue is edited
    # while a conversion runs, identity does not.
    started = Signal(object)
    finished = Signal(object, str)
    failed = Signal(object, str)


class ConversionWorker(QRunnable):
    """Runs a single item's conversion on a QThreadPool worker thread.

    Only ever touches widgets through the emitted signals (started/finished/
    failed), which the GUI connects with Qt.QueuedConnection semantics
    (the default for cross-thread signal/slot connections).
    """

    def __init__(self, item: QueueItem, options: ConversionOptions):
        super().__init__()
        self.item = item
        self.options = options
        self.signals = WorkerSignals()
        self._start_lock = threading.Lock()
        self._started = False

    def take_from(self, pool: QThreadPool) -> bool:
        """Pull this worker out of `pool` if it has not started; True if it did.

        A started worker deletes its C++ half on its own thread when it ends,
        so `tryTake` may only see one that has not. The lock is what holds it
        there: `run` cannot begin while this looks.
        """
        with self._start_lock:
            return not self._started and pool.tryTake(self)

    def run(self) -> None:
        with self._start_lock:
            self._started = True
        self.signals.started.emit(self.item)
        try:
            markdown_text = convert_item(self.item, self.options)
        except Exception as exc:  # noqa: BLE001 - must catch everything per-item
            self.signals.failed.emit(self.item, str(exc))
        else:
            self.signals.finished.emit(self.item, markdown_text)
