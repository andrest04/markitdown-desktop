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

import contextlib
import errno
import os
import re
import socket
import ssl
import threading
import unicodedata
import warnings
import zlib
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from xml.parsers.expat import ExpatError
from zipfile import BadZipFile

# pydub (pulled in by markitdown audio converters) warns on import when
# ffmpeg is missing. Audio transcription is optional; surface real failures
# at conversion time instead of scaring every startup.
warnings.filterwarnings(
    "ignore",
    message=r"Couldn't find ffmpeg or avconv",
    category=RuntimeWarning,
    module=r"pydub\.utils",
)

import requests
import shiboken6
from markitdown import (
    FileConversionException,
    MarkItDown,
    MissingDependencyException,
    StreamInfo,
    UnsupportedFormatException,
)
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from requests.exceptions import RequestException

from app.core.queue_model import FailureReason, QueueItem, SourceKind

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


def _write_new_file(path: Path, text: str) -> None:
    """Write a file that must not exist yet, leaving nothing behind if that fails.

    A full disk takes the name and refuses the bytes, so without this every retry
    would leave an empty file and push the next one's name along. Creating it first
    is what makes removing it safe: if the name was taken by then, this raises here.
    """
    path.touch(exist_ok=False)
    try:
        path.write_text(text, encoding="utf-8")
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def save_copy(path: str | Path, text: str) -> None:
    """Write where the person chose, replacing a file they agreed to replace.

    One created here goes again if the write fails. One that was there stays,
    whatever the failed write left in it.
    """
    existed = os.path.exists(path)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        if not existed:
            with contextlib.suppress(OSError):
                os.unlink(path)
        raise


def auto_save_markdown(item: QueueItem, markdown_text: str, downloads_dir: Path | None = None) -> Path:
    """Write `markdown_text` to the Downloads folder using a name derived from
    the item's source, avoiding collisions. Returns the path written to."""
    directory = downloads_dir if downloads_dir is not None else get_downloads_dir()
    base_name = sanitize_filename(default_basename(item))
    path = unique_download_path(directory, base_name)
    _write_new_file(path, markdown_text)
    return path


@dataclass(frozen=True)
class ExportFailure:
    item: QueueItem
    reason: FailureReason
    detail: str  # raw OS text


@dataclass
class ExportResult:
    """What `export_markdown` wrote, and which items failed and why."""

    written: list[Path] = field(default_factory=list)
    failures: list[ExportFailure] = field(default_factory=list)


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
            _write_new_file(path, item.markdown_result or "")
        except OSError as exc:
            result.failures.append(ExportFailure(item, classify_save_error(exc), str(exc)))
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


# Seconds to wait for a connection, then for the next bytes from the server. The
# read limit covers each gap in the data, so a large steady download is not cut.
URL_TIMEOUT = (10, 60)


class _TimeoutSession(requests.Session):
    """Gives up on a silent server: requests waits forever unless told otherwise.

    `send` is where every request passes, redirects included. markitdown only sets
    its Accept header on a session of its own, so that comes along here.
    """

    def __init__(self):
        super().__init__()
        self.headers["Accept"] = "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1"

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = URL_TIMEOUT
        return super().send(request, **kwargs)


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
        kwargs: dict = {"enable_plugins": self.enable_plugins, "requests_session": _TimeoutSession()}
        if self.docintel_enabled and self.docintel_endpoint.strip():
            kwargs["docintel_endpoint"] = self.docintel_endpoint.strip()
        if self.cu_enabled and self.cu_endpoint.strip():
            kwargs["cu_endpoint"] = self.cu_endpoint.strip()
            if self.cu_analyzer_id.strip():
                kwargs["cu_analyzer_id"] = self.cu_analyzer_id.strip()
        return MarkItDown(**kwargs)


class NoTextFound(Exception):
    """A conversion succeeded and produced nothing a reader could see.

    markitdown raises nothing for this, which is what happens to a damaged `.png`
    and also to a sound one holding no extractable text, so it says nothing about
    the file's health. It carries no message: the interface translates the reason.
    """


# Separators, control and format characters. `str.strip` misses the format ones,
# such as the byte order mark an empty text file comes back as.
_INVISIBLE_CATEGORIES = {"Zs", "Zl", "Zp", "Cc", "Cf"}


def _has_visible_text(text: str) -> bool:
    return any(unicodedata.category(char) not in _INVISIBLE_CATEGORIES for char in text)


def convert_item(item: QueueItem, options: ConversionOptions) -> str:
    """Run an actual MarkItDown conversion for a single queue item.

    Kept independent of Qt so it can be exercised directly (e.g. in tests
    or a smoke-test script) without a QApplication/thread pool.

    Raises NoTextFound rather than returning text with nothing in it, so no
    caller ends up writing an empty `.md`.
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

    text = result.text_content
    if not _has_visible_text(text or ""):
        raise NoTextFound()
    return text


# Every one of these is an OSError, or an IOError in the case of requests, so
# they have to be checked before the file errors below.
_NETWORK_ERRORS = (RequestException, URLError, ConnectionError, TimeoutError, socket.gaierror, ssl.SSLError)
# These come from optional libraries, so they go by class name instead of an
# import: speech_recognition's RequestError, and Azure's failures to reach the
# service. Azure's HttpResponseError is left out, since the service did answer.
_NETWORK_ERROR_NAMES = {"RequestError", "ServiceRequestError", "ServiceResponseError"}
# What a format parser raises on contents it cannot make sense of. The names are
# pdfminer's, xlrd's and Pillow's, optional like the ones above.
_DAMAGED_FILE_ERRORS = (BadZipFile, zlib.error, ExpatError)
_DAMAGED_FILE_ERROR_NAMES = {"PDFSyntaxError", "CompDocError", "XLRDError", "UnidentifiedImageError"}
_NO_ROOM = {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}
_NOT_ALLOWED = {errno.EACCES, errno.EPERM, errno.EROFS}


def _has_class_named(error: Exception, names: set[str]) -> bool:
    return any(cls.__name__ in names for cls in type(error).__mro__)


def _is_network_error(error: Exception) -> bool:
    return isinstance(error, _NETWORK_ERRORS) or _has_class_named(error, _NETWORK_ERROR_NAMES)


def _is_damaged_file_error(error: Exception) -> bool:
    return isinstance(error, _DAMAGED_FILE_ERRORS) or _has_class_named(error, _DAMAGED_FILE_ERROR_NAMES)


def _classify_attempts(error: FileConversionException) -> FailureReason:
    """A converter recognized the file and then failed on it.

    markitdown wraps what each attempt raised, and the source already opened by
    then, so a FileNotFoundError here is a helper program, such as ffmpeg for
    audio. Telling someone their file is damaged is a claim about their file, so
    it takes an error that says so. A bare ValueError or KeyError does not: a
    library bug raises those as well, and the raw text stays in the detail pane.
    """
    errors = [attempt.exc_info[1] for attempt in error.attempts or [] if attempt.exc_info]
    if any(isinstance(exc, (MissingDependencyException, FileNotFoundError)) for exc in errors):
        return FailureReason.MISSING_DEPENDENCY
    if any(_is_network_error(exc) for exc in errors):
        return FailureReason.NETWORK
    if any(isinstance(exc, PermissionError) for exc in errors):
        return FailureReason.PERMISSION_DENIED
    if any(_is_damaged_file_error(exc) for exc in errors):
        return FailureReason.UNREADABLE_FILE
    return FailureReason.GENERIC


def classify_conversion_error(error: Exception) -> FailureReason:
    """Sort what `convert_item` raised into a reason the interface can translate."""
    if isinstance(error, NoTextFound):
        return FailureReason.NO_TEXT
    if isinstance(error, UnsupportedFormatException):
        return FailureReason.UNSUPPORTED_FORMAT
    if isinstance(error, MissingDependencyException):
        return FailureReason.MISSING_DEPENDENCY
    if isinstance(error, FileConversionException):
        return _classify_attempts(error)
    if _is_network_error(error):
        return FailureReason.NETWORK
    if isinstance(error, FileNotFoundError):
        return FailureReason.FILE_NOT_FOUND
    if isinstance(error, PermissionError):
        return FailureReason.PERMISSION_DENIED
    if isinstance(error, OSError):
        return FailureReason.UNREADABLE_FILE
    return FailureReason.GENERIC


def classify_save_error(error: OSError) -> FailureReason:
    """Sort a failed write by errno. Windows error codes arrive mapped onto it."""
    if error.errno in _NO_ROOM:
        return FailureReason.DISK_FULL
    if isinstance(error, PermissionError) or error.errno in _NOT_ALLOWED:
        return FailureReason.PERMISSION_DENIED
    return FailureReason.SAVE_GENERIC


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
    failed = Signal(object, object, str)  # item, FailureReason, raw message


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

        A taken worker is the caller's to delete, and PySide does not take that
        on: it still pins the Python half, and the item with it, for good.
        """
        with self._start_lock:
            if self._started or not pool.tryTake(self):
                return False
        shiboken6.delete(self)
        return True

    def run(self) -> None:
        with self._start_lock:
            self._started = True
        self.signals.started.emit(self.item)
        try:
            markdown_text = convert_item(self.item, self.options)
        except Exception as exc:  # noqa: BLE001 - must catch everything per-item
            self.signals.failed.emit(self.item, classify_conversion_error(exc), str(exc))
        else:
            self.signals.finished.emit(self.item, markdown_text)
