"""A server that accepts a link and then goes quiet ends as a failure, not a hang.

These run the real markitdown against real local sockets, since which exception
arrives, and from how deep, is what they pin down. Conversions run off the test's
thread: without a timeout they would never return.
"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import requests
from qt_support import pump_until, qapp, settle

from app.core.converter import (
    ConversionOptions,
    classify_conversion_error,
    convert_item,
)
from app.core.queue_model import (
    FailureReason,
    ItemStatus,
    QueueItem,
    QueueTableModel,
    SourceKind,
)

# Short enough to keep the suite quick, long enough for a loopback connection.
SHORT_TIMEOUT = (2, 0.4)
# How long a test waits before calling a conversion stuck.
PATIENCE = 8.0
HEADERS = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"


class _LocalServer:
    """Accepts connections, reads the request, then does what `behavior` says."""

    def __init__(self, behavior=None):
        self._behavior = behavior
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(0.05)
        self.requests: list[bytes] = []
        self._connections: list[socket.socket] = []
        self._threads = [threading.Thread(target=self._accept, daemon=True)]
        self._threads[0].start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._listener.getsockname()[1]}/page.txt"

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._connections.append(connection)
            thread = threading.Thread(target=self._serve, args=(connection,), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _serve(self, connection: socket.socket) -> None:
        try:
            self.requests.append(connection.recv(65536))
            if self._behavior is not None:
                self._behavior(connection, self._stop)
            self._stop.wait()
        except OSError:
            pass  # The client gave up, which is the point of most of these.

    def close(self) -> None:
        self._stop.set()
        for connection in self._connections:
            connection.close()
        self._listener.close()
        for thread in self._threads:
            thread.join(5)


def _url_item(url: str) -> QueueItem:
    return QueueItem(source=url, kind=SourceKind.URL, display_name="page.txt")


class _Outcome:
    def __init__(self):
        self.text = None
        self.error = None


def _convert_in_background(url: str) -> tuple[threading.Thread, _Outcome]:
    outcome = _Outcome()

    def run():
        try:
            outcome.text = convert_item(_url_item(url), ConversionOptions())
        except Exception as exc:  # noqa: BLE001 - the test inspects whatever arrives
            outcome.error = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


class UrlTimeoutTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("app.core.converter.URL_TIMEOUT", SHORT_TIMEOUT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, behavior=None) -> _LocalServer:
        server = _LocalServer(behavior)
        self.addCleanup(server.close)
        return server

    def outcome_of(self, url: str) -> _Outcome:
        thread, outcome = _convert_in_background(url)
        thread.join(PATIENCE)
        self.assertFalse(thread.is_alive(), f"the conversion was still waiting after {PATIENCE} seconds")
        return outcome


class SilentServerTests(UrlTimeoutTestCase):
    def test_a_server_that_never_answers_is_a_network_failure(self):
        outcome = self.outcome_of(self.serve().url)
        self.assertIsInstance(outcome.error, requests.exceptions.ReadTimeout)
        self.assertIs(classify_conversion_error(outcome.error), FailureReason.NETWORK)

    def test_a_server_that_stops_halfway_is_a_network_failure(self):
        def send_some(connection, _stop):
            connection.sendall(HEADERS + b"the first part")

        outcome = self.outcome_of(self.serve(send_some).url)
        # requests reports a read timeout in the body as a ConnectionError.
        self.assertIsInstance(outcome.error, requests.exceptions.RequestException)
        self.assertIs(classify_conversion_error(outcome.error), FailureReason.NETWORK)


class SteadyServerTests(UrlTimeoutTestCase):
    def test_slow_steady_data_is_not_cut_off(self):
        # Takes well over the read timeout overall, with no gap reaching it.
        gap = SHORT_TIMEOUT[1] / 4
        chunks = 12
        self.assertGreater(gap * chunks, SHORT_TIMEOUT[1] * 2)

        def send_steadily(connection, _stop):
            connection.sendall(HEADERS)
            for number in range(chunks):
                time.sleep(gap)
                connection.sendall(f"line {number}\n".encode())
            connection.close()

        outcome = self.outcome_of(self.serve(send_steadily).url)
        self.assertIsNone(outcome.error)
        self.assertIn(f"line {chunks - 1}", outcome.text)

    def test_markitdown_still_asks_for_markdown_first(self):
        # markitdown sets this header only on a session of its own.
        def answer(connection, _stop):
            connection.sendall(HEADERS + b"some text")
            connection.close()

        server = self.serve(answer)
        self.assertIsNone(self.outcome_of(server.url).error)
        request = server.requests[0].decode("ascii").lower()
        self.assertIn("accept: text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1", request)


class _RecordingAdapter(requests.adapters.HTTPAdapter):
    def __init__(self):
        super().__init__()
        self.timeouts: list = []

    def send(self, request, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response.url = request.url
        return response


class TimeoutDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        with mock.patch("app.core.converter.MarkItDown") as engine:
            ConversionOptions().build_markitdown()
        self.session = engine.call_args.kwargs["requests_session"]
        self.adapter = _RecordingAdapter()
        self.session.mount("http://", self.adapter)

    def test_the_default_is_a_connect_and_read_pair(self):
        from app.core import converter

        connect, read = converter.URL_TIMEOUT
        self.assertLess(connect, read)

    def test_a_request_without_a_timeout_gets_the_default(self):
        from app.core import converter

        self.session.get("http://example.invalid/")
        self.assertEqual(self.adapter.timeouts, [converter.URL_TIMEOUT])

    def test_a_timeout_from_the_caller_is_respected(self):
        self.session.get("http://example.invalid/", timeout=0.25)
        self.session.get("http://example.invalid/", timeout=(1, 2))
        self.assertEqual(self.adapter.timeouts, [0.25, (1, 2)])


class QueueItemTests(UrlTimeoutTestCase):
    def test_a_silent_server_leaves_the_item_failed_with_a_reason(self):
        from app.core.conversion_queue import ConversionQueue

        qapp()
        with tempfile.TemporaryDirectory() as home, mock.patch("pathlib.Path.home", return_value=Path(home)):
            model = QueueTableModel()
            queue = ConversionQueue(model)
            server = self.serve()
            item = _url_item(server.url)
            model.add_item(item)
            queue.enqueue([item], ConversionOptions())
            # Cleanups run last in, first out: free a stuck worker, then wait for it.
            self.addCleanup(settle)
            self.addCleanup(server.close)

            self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR, PATIENCE), item.status)
            self.assertIs(item.error_reason, FailureReason.NETWORK)
            self.assertEqual(list(Path(home).rglob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
