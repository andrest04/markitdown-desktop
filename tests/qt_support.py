"""Shared fixtures for the Qt test suite (stdlib unittest only).

Isolation rules enforced here:
- `Path.home` points at a temp folder, so nothing reaches the real Downloads.
- `app.ui.main_window.QSettings` is replaced, so native settings stay untouched.
- The global i18n manager is reset to English around every test.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent, QThreadPool
from PySide6.QtWidgets import QApplication

from app.i18n import LANG_EN, SETTINGS_KEY
from app.i18n import manager as i18n_manager


def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def process_events() -> None:
    qapp().processEvents()


def pump_until(predicate, timeout: float = 5.0) -> bool:
    """Process Qt events until `predicate()` is true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process_events()
        if predicate():
            return True
        time.sleep(0.005)
    process_events()
    return predicate()


def settle() -> None:
    """Wait for every pool worker, then deliver their queued signals."""
    QThreadPool.globalInstance().waitForDone(10_000)
    for _ in range(3):
        process_events()


class FakeSettings:
    """In-memory stand-in for QSettings."""

    def __init__(self, *_args, **_kwargs):
        self.values: dict = {SETTINGS_KEY: LANG_EN}

    def value(self, key, default=None, type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class GatedConverter:
    """Stand-in for `convert_item`; each call blocks until its item is released."""

    def __init__(self):
        self._lock = threading.Lock()
        self._gates: dict[str, threading.Event] = {}
        self._open_all = threading.Event()
        self.calls: list = []
        self.options_seen: list = []
        self.threads: list = []
        self.failures: dict[str, str] = {}

    def _gate(self, name: str) -> threading.Event:
        with self._lock:
            return self._gates.setdefault(name, threading.Event())

    def __call__(self, item, options):
        with self._lock:
            self.calls.append(item)
            self.options_seen.append(options)
            self.threads.append(threading.current_thread())
        gate = self._gate(item.display_name)
        deadline = time.monotonic() + 10
        while not gate.is_set() and not self._open_all.is_set() and time.monotonic() < deadline:
            time.sleep(0.002)
        gate.clear()
        failure = self.failures.get(item.display_name)
        if failure is not None:
            raise RuntimeError(failure)
        return f"# converted {item.display_name}"

    def release(self, name: str) -> None:
        self._gate(name).set()

    def release_all(self) -> None:
        self._open_all.set()

    def hold_all(self) -> None:
        """Undo release_all(): later calls block on their gate again."""
        self._open_all.clear()

    def call_count(self, name: str | None = None) -> int:
        with self._lock:
            if name is None:
                return len(self.calls)
            return sum(1 for item in self.calls if item.display_name == name)


class QtTestCase(unittest.TestCase):
    """Isolated environment with a stubbed converter and a temp home folder."""

    def setUp(self) -> None:
        qapp()
        i18n_manager._language = LANG_EN
        self.addCleanup(setattr, i18n_manager, "_language", LANG_EN)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.downloads = self.home / "Downloads"
        self.sources = self.tmp / "sources"
        self.sources.mkdir()

        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.converter = GatedConverter()
        patcher = mock.patch("app.core.converter.convert_item", self.converter)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Runs before the patches above are undone: no worker may outlive a test.
        self.addCleanup(self._drain_workers)

        pool = QThreadPool.globalInstance()
        previous = pool.maxThreadCount()
        pool.setMaxThreadCount(max(previous, 4))
        self.addCleanup(pool.setMaxThreadCount, previous)

    def _drain_workers(self) -> None:
        self.converter.release_all()
        settle()

    def make_source(self, name: str) -> str:
        path = self.sources / name
        path.write_text("content", encoding="utf-8")
        return str(path)

    def downloaded_names(self) -> list[str]:
        if not self.downloads.exists():
            return []
        return sorted(p.name for p in self.downloads.iterdir())


class WindowTestCase(QtTestCase):
    """Adds a real MainWindow built on fake settings."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch("app.ui.main_window.QSettings", FakeSettings)
        patcher.start()
        self.addCleanup(patcher.stop)

        from app.ui.main_window import MainWindow

        self.window = MainWindow()
        self.addCleanup(self._dispose_window)

    def _dispose_window(self) -> None:
        self.converter.release_all()
        settle()
        self.window.close()
        self.window.deleteLater()
        # processEvents() alone never runs deferred deletes; leftover windows
        # would slow every later global stylesheet change.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        process_events()

    def add_sources(self, *names: str) -> list[str]:
        paths = [self.make_source(name) for name in names]
        self.window._add_paths(paths)
        return paths

    def wait_started(self, count: int) -> None:
        self.assertTrue(
            pump_until(lambda: self.converter.call_count() >= count),
            f"expected {count} conversions to start, saw {self.converter.call_count()}",
        )

    def item_named(self, name: str):
        for item in self.window.model.items():
            if item.display_name == name:
                return item
        self.fail(f"{name} is not in the queue")

    def progress_state(self) -> tuple[int, int, bool]:
        bar = self.window.progress_bar
        return bar.value(), bar.maximum(), not bar.isHidden()
