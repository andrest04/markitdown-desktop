"""Closing with work in flight asks first, and "close anyway" really ends the process.

The dialog is never opened: `QMessageBox.exec` is replaced by a stand-in that looks
at the box and clicks one of its buttons. The process tests run the real `main()` in
a child process, because what they pin down is how that process ends.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox
from qt_support import FakeSettings, WindowTestCase, process_events, pump_until, settle

from app.core.queue_model import ItemStatus
from app.i18n import LANG_ES, tr
from app.i18n import manager as i18n_manager

REPO_ROOT = Path(__file__).resolve().parent.parent
# Generous for a slow first import in CI; only a process that lingers ever waits this long.
PROCESS_PATIENCE = 120


class _DialogStandIn:
    """Replaces `QMessageBox.exec`: records what the box says, then clicks `answer`."""

    def __init__(self, answer: str | None):
        self.answer = answer
        self.shown: list[dict] = []

    def __call__(self, box: QMessageBox) -> int:
        buttons = {button.text(): button for button in box.buttons()}
        self.shown.append(
            {
                "title": box.windowTitle(),
                "text": box.text(),
                "buttons": sorted(buttons),
                "default": box.defaultButton().text(),
                "escape": box.escapeButton().text(),
            }
        )
        if self.answer is not None:
            buttons[tr(self.answer)].click()
        return 0


class CloseDialogTests(WindowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.window.settings = FakeSettings()
        self.window.show()
        pool = QThreadPool.globalInstance()
        previous = pool.maxThreadCount()
        pool.setMaxThreadCount(1)
        self.addCleanup(pool.setMaxThreadCount, previous)

    def dialog(self, answer: str | None = None) -> _DialogStandIn:
        stand_in = _DialogStandIn(answer)
        # A plain function, so that it binds to the box as a method would.
        patcher = mock.patch.object(QMessageBox, "exec", lambda box: stand_in(box))
        patcher.start()
        self.addCleanup(patcher.stop)
        return stand_in

    def test_nothing_in_flight_closes_without_asking(self):
        dialog = self.dialog()
        self.add_sources("a.txt")
        self.converter.release_all()
        settle()

        self.assertTrue(self.window.close())

        self.assertEqual(dialog.shown, [])
        self.assertFalse(self.window.isVisible())
        self.assertIn("window/geometry", self.window.settings.values)

    def test_an_empty_window_closes_without_asking(self):
        dialog = self.dialog()
        self.assertTrue(self.window.close())
        self.assertEqual(dialog.shown, [])

    def test_it_asks_with_the_count_and_keeps_converting_by_default(self):
        dialog = self.dialog("msgbox.close_busy.keep")
        self.add_sources("a.txt", "b.txt", "c.txt")
        self.wait_started(1)

        self.window.close()

        self.assertEqual(len(dialog.shown), 1)
        shown = dialog.shown[0]
        self.assertIn("3", shown["text"])
        self.assertEqual(shown["text"], tr("msgbox.close_busy.text.other", count=3))
        self.assertEqual(shown["buttons"], sorted([tr("msgbox.close_busy.keep"), tr("msgbox.close_busy.close")]))
        self.assertEqual(shown["default"], tr("msgbox.close_busy.keep"))
        self.assertEqual(shown["escape"], tr("msgbox.close_busy.keep"))

    def test_one_conversion_reads_as_one(self):
        dialog = self.dialog("msgbox.close_busy.keep")
        self.add_sources("a.txt")
        self.wait_started(1)

        self.window.close()

        self.assertEqual(dialog.shown[0]["text"], tr("msgbox.close_busy.text.one"))

    def test_the_question_follows_the_language(self):
        i18n_manager._language = LANG_ES
        dialog = self.dialog("msgbox.close_busy.keep")
        self.add_sources("a.txt", "b.txt")
        self.wait_started(1)

        self.window.close()

        self.assertIn("Hay 2 conversiones", dialog.shown[0]["text"])

    def test_keep_converting_loses_nothing(self):
        self.dialog("msgbox.close_busy.keep")
        self.add_sources("a.txt", "b.txt")
        self.wait_started(1)

        self.assertFalse(self.window.close())

        self.assertTrue(self.window.isVisible())
        self.assertNotIn("window/geometry", self.window.settings.values)
        self.converter.release_all()
        settle()
        self.assertEqual(self.item_named("a.txt").status, ItemStatus.DONE)
        self.assertEqual(self.item_named("b.txt").status, ItemStatus.DONE)
        self.assertEqual(self.downloaded_names(), ["a.md", "b.md"])

    def test_a_box_closed_without_a_button_keeps_the_window(self):
        self.dialog(None)
        self.add_sources("a.txt")
        self.wait_started(1)

        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())

    def test_after_keeping_it_asks_again_only_while_there_is_work(self):
        dialog = self.dialog("msgbox.close_busy.keep")
        self.add_sources("a.txt")
        self.wait_started(1)
        self.window.close()
        self.converter.release_all()
        settle()

        self.assertTrue(self.window.close())
        self.assertEqual(len(dialog.shown), 1)

    def test_close_anyway_cancels_what_has_not_started(self):
        self.dialog("msgbox.close_busy.close")
        self.add_sources("running.txt", "queued.txt")
        self.wait_started(1)

        self.assertTrue(self.window.close())

        self.assertFalse(self.window.isVisible())
        self.assertIn("window/geometry", self.window.settings.values)
        self.converter.release_all()
        settle()
        self.assertEqual(self.converter.call_count("running.txt"), 1)
        self.assertEqual(self.converter.call_count("queued.txt"), 0)

    def test_a_removed_item_still_running_is_not_worth_asking_about(self):
        dialog = self.dialog()
        self.add_sources("a.txt")
        self.wait_started(1)
        self.window.action_clear_all()
        process_events()

        self.assertTrue(self.window.close())
        self.assertEqual(dialog.shown, [])

    def test_the_count_leaves_out_removed_items(self):
        dialog = self.dialog("msgbox.close_busy.keep")
        self.add_sources("running.txt", "kept.txt")
        self.wait_started(1)
        running = self.item_named("running.txt")
        self.assertTrue(pump_until(lambda: running.status == ItemStatus.CONVERTING))
        self.window.model.remove_rows([0])
        self.window.conversion_queue.discard([running])

        self.window.close()

        self.assertEqual(dialog.shown[0]["text"], tr("msgbox.close_busy.text.one"))


_DRIVER = r"""
import sys
import threading
import time
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QMessageBox
from qt_support import FakeSettings

import main
from app.i18n import tr
from app.ui.main_window import MainWindow

mode, hold, home = sys.argv[1], float(sys.argv[2]), Path(sys.argv[3])
sources = sys.argv[4:]
running = threading.Event()


class Settings(FakeSettings):
    def sync(self):
        print("flushed", "window/geometry" in self.values, flush=True)


def convert(item, options):
    print("started", item.display_name, flush=True)
    running.set()
    time.sleep(hold)
    return "# text"


def click_close_anyway(box):
    print("asked", flush=True)
    next(b for b in box.buttons() if b.text() == tr("msgbox.close_busy.close")).click()
    return 0


class Driven(MainWindow):
    def show(self):
        super().show()
        self.poll = QTimer(self)
        self.poll.setInterval(10)
        self.poll.timeout.connect(self.close_once_running)
        if mode == "busy":
            QThreadPool.globalInstance().setMaxThreadCount(1)
            self._add_paths(sources)
        self.poll.start()

    def close_once_running(self):
        if mode != "busy" or running.is_set():
            self.poll.stop()
            self.close()


for patcher in (
    mock.patch("pathlib.Path.home", return_value=home),
    mock.patch("app.ui.main_window.QSettings", Settings),
    mock.patch("app.core.converter.convert_item", convert),
    mock.patch.object(main, "MainWindow", Driven),
    mock.patch.object(QMessageBox, "exec", click_close_anyway),
):
    patcher.start()

sys.exit(main.main())
"""


class ProcessExitTests(unittest.TestCase):
    """How the real `main()` ends. The child process only ever sees a temp home."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        self.sources = []
        for name in ("running.txt", "queued.txt"):
            path = Path(tmp.name) / name
            path.write_text("content", encoding="utf-8")
            self.sources.append(str(path))

    def run_app(self, mode: str, hold: float) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": str(REPO_ROOT / "tests"),
        }
        process = subprocess.Popen(
            [sys.executable, "-c", _DRIVER, mode, str(hold), str(self.home), *self.sources],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=PROCESS_PATIENCE)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(f"the process was still alive after {PROCESS_PATIENCE} seconds\n{stdout}\n{stderr}")
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def test_close_anyway_ends_the_process_with_a_worker_still_running(self):
        # The worker would run far past the patience above.
        result = self.run_app("busy", hold=PROCESS_PATIENCE * 5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RuntimeError", result.stderr)
        self.assertNotIn("Signal source has been deleted", result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("asked", lines)
        self.assertIn("started running.txt", lines)
        self.assertNotIn("started queued.txt", lines)
        self.assertIn("flushed True", lines)
        self.assertEqual(list(self.home.rglob("*.md")), [])

    def test_a_close_with_nothing_running_ends_as_usual(self):
        result = self.run_app("idle", hold=0)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RuntimeError", result.stderr)
        lines = result.stdout.splitlines()
        self.assertNotIn("asked", lines)
        self.assertIn("flushed True", lines)


if __name__ == "__main__":
    unittest.main()
