"""Failures reach the person as a reason in their language, with the raw text kept.

The conversion cases trigger the failure for real through `convert_item`, because
which exception arrives is exactly what is being pinned, and it differs from what
a reading of markitdown suggests: a text file renamed `.pdf` converts happily.
"""
from __future__ import annotations

import errno
import socket
import sys
import tempfile
import threading
import unittest
import warnings
import wave
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import markitdown
import speech_recognition
from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from markitdown import FileConversionException
from markitdown._exceptions import FailedConversionAttempt
from qt_support import WindowTestCase, process_events, pump_until, settle

from app.core.converter import (
    ConversionOptions,
    classify_conversion_error,
    classify_save_error,
    convert_item,
    export_markdown,
)
from app.core.queue_model import FailureReason, ItemStatus, QueueItem, SourceKind
from app.i18n import LANG_EN, LANG_ES, TRANSLATIONS, tr
from app.i18n import manager as i18n_manager
from app.ui.queue_delegate import detail_status, row_status_text


def _file_item(path: Path) -> QueueItem:
    return QueueItem(source=str(path), kind=SourceKind.FILE, display_name=path.name)


def _url_item(url: str) -> QueueItem:
    return QueueItem(source=url, kind=SourceKind.URL, display_name=url)


class RealConversionFailureTests(unittest.TestCase):
    def setUp(self):
        catcher = warnings.catch_warnings()
        catcher.__enter__()
        self.addCleanup(catcher.__exit__, None, None, None)
        warnings.simplefilter("ignore")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def reason_for(self, item: QueueItem) -> FailureReason:
        with self.assertRaises(Exception) as caught:
            convert_item(item, ConversionOptions())
        return classify_conversion_error(caught.exception)

    def write(self, name: str, data: bytes) -> QueueItem:
        path = self.folder / name
        path.write_bytes(data)
        return _file_item(path)

    def test_a_missing_file(self):
        self.assertIs(self.reason_for(_file_item(self.folder / "gone.txt")), FailureReason.FILE_NOT_FOUND)

    def test_an_unsupported_format(self):
        item = self.write("data.dat", bytes(range(256)) * 4)
        self.assertIs(self.reason_for(item), FailureReason.UNSUPPORTED_FORMAT)

    def test_damaged_documents(self):
        zip_header = b"PK\x03\x04" + b"\0" * 200
        for name, data in (
            ("empty.pdf", b""),
            ("broken.pdf", b"%PDF-1.7\n" + b"garbage\n" * 30),
            ("broken.docx", zip_header),
            ("broken.xlsx", zip_header),
            ("broken.pptx", zip_header),
            ("broken.zip", zip_header),
            ("broken.epub", zip_header),
            # An OLE2 header with nothing behind it reaches xlrd's CompDocError.
            ("broken.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600),
            ("broken.rss", b"<rss><<<"),
        ):
            with self.subTest(name=name):
                self.assertIs(self.reason_for(self.write(name, data)), FailureReason.UNREADABLE_FILE)

    def _pcm_wav(self, name: str) -> QueueItem:
        path = self.folder / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 1600)
        return _file_item(path)

    def _recognizer_raises(self, error: Exception):
        # The one call that leaves the machine, so no test reaches the real service.
        return mock.patch.object(speech_recognition.Recognizer, "recognize_google", side_effect=error)

    def test_a_good_recording_while_offline_is_the_network_not_the_file(self):
        error = speech_recognition.RequestError("recognition connection failed")
        with self._recognizer_raises(error):
            self.assertIs(self.reason_for(self._pcm_wav("good.wav")), FailureReason.NETWORK)

    def test_a_recording_with_no_recognizable_speech_is_not_called_damaged(self):
        with self._recognizer_raises(speech_recognition.UnknownValueError()):
            self.assertIs(self.reason_for(self._pcm_wav("silent.wav")), FailureReason.GENERIC)

    def test_permission_denied(self):
        # A patch, because chmod cannot deny the owner on Windows or root elsewhere.
        item = self.write("locked.txt", b"text")
        real_open = open

        def deny_this_file(path, *args, **kwargs):
            if path == item.source:
                raise PermissionError(errno.EACCES, "Permission denied", path)
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", deny_this_file):
            self.assertIs(self.reason_for(item), FailureReason.PERMISSION_DENIED)

    def test_a_missing_optional_dependency(self):
        try:
            raise ImportError("no module named pdfminer")
        except ImportError:
            exc_info = sys.exc_info()
        item = self.write("empty.pdf", b"")
        with mock.patch("markitdown.converters._pdf_converter._dependency_exc_info", exc_info):
            self.assertIs(self.reason_for(item), FailureReason.MISSING_DEPENDENCY)

    def test_a_refused_connection(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertIs(self.reason_for(_url_item(f"http://127.0.0.1:{port}/a.html")), FailureReason.NETWORK)

    def test_a_page_that_is_not_there(self):
        class NotFound(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_error(404)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), NotFound)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        url = f"http://127.0.0.1:{server.server_address[1]}/a.html"
        self.assertIs(self.reason_for(_url_item(url)), FailureReason.NETWORK)


class ClassificationTests(unittest.TestCase):
    """Cases a scratch file cannot trigger on every machine."""

    def _attempts(self, *errors: Exception) -> FileConversionException:
        attempts = [FailedConversionAttempt(object(), (type(e), e, None)) for e in errors]
        return FileConversionException(attempts=attempts)

    def test_a_helper_program_that_is_not_installed_is_a_missing_component(self):
        # What pydub raises for an mp3 when ffmpeg is absent, seen on a real file.
        error = FileNotFoundError(2, "The system cannot find the file specified")
        self.assertIs(classify_conversion_error(self._attempts(error)), FailureReason.MISSING_DEPENDENCY)

    def test_a_dependency_reason_beats_the_other_attempts(self):
        missing = markitdown.MissingDependencyException("install it")
        self.assertIs(
            classify_conversion_error(self._attempts(ValueError("x"), missing)),
            FailureReason.MISSING_DEPENDENCY,
        )

    def test_an_image_the_library_cannot_identify(self):
        class UnidentifiedImageError(OSError):
            """PIL's real class derives from OSError, which is what classifies it."""

        error = UnidentifiedImageError("cannot identify image file")
        self.assertIs(classify_conversion_error(error), FailureReason.UNREADABLE_FILE)
        self.assertIs(classify_conversion_error(self._attempts(error)), FailureReason.UNREADABLE_FILE)

    def test_network_errors_inside_an_attempt_are_the_network_reason(self):
        class ConnectTimeout(speech_recognition.RequestError):
            """A subclass in the same family counts as well."""

        for error in (
            speech_recognition.RequestError("offline"),
            ConnectTimeout("offline"),
            ServiceRequestError("no route"),
            ServiceResponseError("reset"),
            URLError("no route"),
            ConnectionResetError("reset"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertIs(classify_conversion_error(self._attempts(error)), FailureReason.NETWORK)

    def test_a_url_error_is_the_network_outside_an_attempt_too(self):
        # URLError is an OSError, which would otherwise read as an unreadable file.
        self.assertIs(classify_conversion_error(URLError("no route")), FailureReason.NETWORK)

    def test_an_unknown_cause_never_claims_the_file_is_damaged(self):
        for error in (
            TypeError("library bug"),
            ValueError("x"),
            KeyError("x"),
            HttpResponseError("401 from the service"),
            OSError("something else"),
            RuntimeError("boom"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertIs(classify_conversion_error(self._attempts(error)), FailureReason.GENERIC)

    def test_a_format_error_is_evidence_of_damage(self):
        class PDFSyntaxError(Exception):
            """Stands in for pdfminer's, which goes by name since it is optional."""

        for error in (zlib.error("bad data"), PDFSyntaxError("no /Root")):
            with self.subTest(error=type(error).__name__):
                self.assertIs(
                    classify_conversion_error(self._attempts(TypeError("other attempt"), error)),
                    FailureReason.UNREADABLE_FILE,
                )

    def test_anything_else_is_the_generic_reason(self):
        self.assertIs(classify_conversion_error(RuntimeError("boom")), FailureReason.GENERIC)
        self.assertIs(classify_conversion_error(FileConversionException()), FailureReason.GENERIC)

    def test_save_errors_read_errno_never_the_text(self):
        for error, reason in (
            (OSError(errno.ENOSPC, "No space left on device"), FailureReason.DISK_FULL),
            (OSError(errno.EACCES, "Permission denied"), FailureReason.PERMISSION_DENIED),
            (OSError(errno.EPERM, "Operation not permitted"), FailureReason.PERMISSION_DENIED),
            (OSError(errno.EROFS, "Read-only file system"), FailureReason.PERMISSION_DENIED),
            (PermissionError("denied"), FailureReason.PERMISSION_DENIED),
            (OSError(errno.EIO, "No space left on device"), FailureReason.SAVE_GENERIC),
            (OSError("disk full"), FailureReason.SAVE_GENERIC),
        ):
            with self.subTest(error=error):
                self.assertIs(classify_save_error(error), reason)

    @unittest.skipUnless(sys.platform.startswith("win"), "winerror is Windows only")
    def test_a_windows_disk_full_error_arrives_with_the_same_errno(self):
        error = OSError(None, "There is not enough space on the disk", None, 112)
        self.assertIs(classify_save_error(error), FailureReason.DISK_FULL)


class TextTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, i18n_manager, "_language", LANG_EN)
        i18n_manager._language = LANG_EN

    def _failed(self, reason=FailureReason.UNREADABLE_FILE, message="cannot identify image file"):
        item = QueueItem(source="/x/a.png", kind=SourceKind.FILE, display_name="a.png")
        item.mark_failed(message, reason)
        return item

    def _not_saved(self, reason=FailureReason.DISK_FULL, message="[Errno 28] No space left on device"):
        item = QueueItem(source="/x/a.png", kind=SourceKind.FILE, display_name="a.png")
        item.mark_converted("# a")
        item.mark_save_failed(message, reason)
        return item

    def test_the_network_reason_also_fits_a_file_needing_a_service(self):
        # A local recording fails this way, and it has no link to speak of.
        self.assertEqual(tr(FailureReason.NETWORK.value), "connection or link unavailable")
        i18n_manager._language = LANG_ES
        self.assertEqual(tr(FailureReason.NETWORK.value), "conexión o enlace no disponible")

    def test_every_reason_exists_in_both_languages_and_differs(self):
        for reason in FailureReason:
            with self.subTest(reason=reason):
                english, spanish = (TRANSLATIONS[lang][reason.value] for lang in (LANG_EN, LANG_ES))
                self.assertNotEqual(english, spanish)

    def test_the_row_and_header_name_the_reason_in_the_interface_language(self):
        item = self._failed()
        self.assertEqual(row_status_text(item), "Failed: damaged or unreadable file")
        self.assertEqual(detail_status(item), "Damaged or unreadable file")
        i18n_manager._language = LANG_ES
        self.assertEqual(row_status_text(item), "Falló: archivo dañado o ilegible")
        self.assertEqual(detail_status(item), "Archivo dañado o ilegible")

    def test_a_save_failure_names_its_reason_too(self):
        item = self._not_saved()
        self.assertEqual(row_status_text(item), "Not saved: disk full")
        i18n_manager._language = LANG_ES
        self.assertEqual(row_status_text(item), "Sin guardar: disco lleno")
        self.assertEqual(detail_status(item), tr("status.save_failed_detail", error="disco lleno"))

    def test_core_stores_the_key_and_the_raw_text(self):
        item = self._failed()
        self.assertIs(item.error_reason, FailureReason.UNREADABLE_FILE)
        self.assertEqual(item.error_message, "cannot identify image file")
        saved = self._not_saved()
        self.assertIs(saved.save_error_reason, FailureReason.DISK_FULL)
        self.assertEqual(saved.save_error, "[Errno 28] No space left on device")

    def test_export_reports_the_reason_and_the_raw_text(self):
        item = QueueItem(source="/x/a.txt", kind=SourceKind.FILE, display_name="a.txt", markdown_result="# a")
        with tempfile.TemporaryDirectory() as folder, mock.patch(
            "pathlib.Path.write_text", side_effect=OSError(errno.ENOSPC, "No space left on device")
        ):
            result = export_markdown([item], folder)
        failure = result.failures[0]
        self.assertIs(failure.item, item)
        self.assertIs(failure.reason, FailureReason.DISK_FULL)
        self.assertIn("No space left", failure.detail)


class WindowTests(WindowTestCase):
    def _fail_with(self, error: Exception):
        with mock.patch("app.core.converter.convert_item", side_effect=error):
            self.add_sources("a.txt")
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.ERROR))
            settle()
        self.window.table_view.selectRow(0)
        process_events()
        return self.item_named("a.txt")

    def test_a_worker_failure_stores_the_reason_and_shows_it_everywhere(self):
        item = self._fail_with(markitdown.UnsupportedFormatException("Could not convert stream"))
        self.assertIs(item.error_reason, FailureReason.UNSUPPORTED_FORMAT)
        self.assertEqual(item.error_message, "Could not convert stream")
        self.assertEqual(self.window.preview_header_status.text(), "Unsupported format")
        self.assertEqual(
            self.window.status_bar.currentMessage(),
            tr("status.conversion_failed", message="unsupported format"),
        )

    def test_the_detail_pane_keeps_the_raw_text(self):
        self._fail_with(markitdown.UnsupportedFormatException("Could not convert stream"))
        self.assertEqual(self.window.preview_error_detail.text(), "Could not convert stream")
        self.assertFalse(self.window.preview_error_detail.isHidden())

    def test_a_live_language_switch_retranslates(self):
        self._fail_with(markitdown.UnsupportedFormatException("Could not convert stream"))
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertEqual(self.window.preview_header_status.text(), "Formato no compatible")
        self.assertEqual(row_status_text(self.item_named("a.txt")), "Falló: formato no compatible")
        self.assertEqual(self.window.preview_error_detail.text(), "Could not convert stream")
        i18n_manager.set_language(LANG_EN, self.window.settings)
        self.assertEqual(self.window.preview_header_status.text(), "Unsupported format")

    def test_a_save_failure_stores_the_errno_reason(self):
        source = self.make_source("a.txt")
        error = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch("pathlib.Path.write_text", side_effect=error):
            self.window._add_paths([source])
            self.converter.release("a.txt")
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
            settle()
        item = self.item_named("a.txt")
        self.assertIs(item.save_error_reason, FailureReason.DISK_FULL)
        self.assertIn("No space left", item.save_error)
        self.window.table_view.selectRow(0)
        process_events()
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertIn("disco lleno", self.window.preview_header_status.text())

    def test_save_copy_failure_gives_the_reason_in_the_interface_language(self):
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
        settle()
        self.window.table_view.selectRow(0)
        i18n_manager.set_language(LANG_ES, self.window.settings)
        with (
            mock.patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(self.tmp / "c.md"), "")),
            mock.patch("builtins.open", side_effect=OSError(errno.ENOSPC, "No space left on device")),
            mock.patch("app.ui.main_window.QMessageBox.warning") as warning,
        ):
            self.window.action_save_current()
        self.assertIn("disco lleno", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
