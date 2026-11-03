"""The shutdown probe reports what it measured, and never fails the CI step."""
from __future__ import annotations

import contextlib
import io
import runpy
import subprocess
import unittest
from unittest import mock

import shutdown_refcount_probe as probe

_ABORTED = -6  # SIGABRT, as subprocess reports it on Linux
_WINDOWS_ABORT = 3


def _finished(code: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=b"", stderr=stderr)


def _children(outcome):
    """Patch the child runs: `outcome(drop)` returns or raises what the run would."""

    def run(command, **_kwargs):
        return outcome(int(command[-1]))

    return mock.patch("subprocess.run", side_effect=run)


def _timed_out_from(first_drop):
    def outcome(drop):
        if drop >= first_drop:
            raise subprocess.TimeoutExpired(cmd="child", timeout=1)
        return _finished(0)

    return outcome


class MarginTests(unittest.TestCase):
    def margin(self, outcome) -> str:
        with _children(outcome):
            return probe._margin("test_x.py")

    def test_a_margin_brackets_where_the_child_starts_crashing(self):
        margin = self.margin(lambda drop: _finished(0 if drop < 300 else _ABORTED))
        low, high = (int(part) for part in margin.split(".."))
        self.assertLess(low, 300)
        self.assertGreaterEqual(high, 300)
        self.assertLessEqual(high - low, probe._RESOLUTION)

    def test_a_crash_with_nothing_dropped_is_named(self):
        for code in (_ABORTED, 134, _WINDOWS_ABORT):
            with self.subTest(code=code):
                self.assertEqual(self.margin(lambda drop, code=code: _finished(code)), "crashes by itself")

    def test_a_timeout_is_not_a_crash(self):
        margin = self.margin(_timed_out_from(0))
        self.assertIn("timed out", margin)
        self.assertNotIn("crash", margin)

    def test_a_timeout_while_bisecting_is_not_a_margin(self):
        margin = self.margin(_timed_out_from(probe._MAX_DROP // 2))
        self.assertIn("timed out", margin)
        self.assertNotIn("..", margin)

    def test_surviving_the_cap_is_not_a_measurement(self):
        margin = self.margin(lambda drop: _finished(0))
        self.assertEqual(margin, f"above {probe._MAX_DROP}, not measured")

    def test_a_child_that_cannot_start_is_reported_with_its_error(self):
        def outcome(drop):
            raise FileNotFoundError("no such interpreter")

        margin = self.margin(outcome)
        self.assertIn("no such interpreter", margin)
        self.assertNotIn("crash", margin)

    def test_an_exception_in_the_child_is_not_a_crash(self):
        stderr = b"Traceback (most recent call last):\n  File x\nImportError: no module named y\n"
        margin = self.margin(lambda drop: _finished(1, stderr))
        self.assertIn("ImportError: no module named y", margin)
        self.assertNotIn("crash", margin)

    def test_a_bug_in_the_probe_stays_on_its_own_line(self):
        def outcome(drop):
            raise ValueError("unexpected")

        self.assertIn("unexpected", self.margin(outcome))


class ReportTests(unittest.TestCase):
    def output_of(self, call) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            call()
        return out.getvalue()

    def test_it_names_each_module_with_its_margin(self):
        def outcome(drop):
            return _finished(0 if drop < 300 else _ABORTED)

        with _children(outcome):
            output = self.output_of(probe.main)
        for name in (probe._BASELINE, "test_shutdown_refcount_probe.py", "test_*.py"):
            self.assertRegex(output, rf"(?m)^{name.replace('*', '[*]')}\s+\d+\.\.\d+$")

    def test_a_failure_in_the_probe_itself_is_printed_not_raised(self):
        with mock.patch.object(probe, "version", side_effect=RuntimeError("no metadata")):
            output = self.output_of(probe.run)
        self.assertIn("no metadata", output)

    def test_the_script_exits_0_when_no_child_can_start(self):
        def outcome(drop):
            raise OSError("spawn failed")

        with _children(outcome), mock.patch("sys.argv", [probe.__file__]), self.assertRaises(SystemExit) as caught:
            self.output_of(lambda: runpy.run_path(probe.__file__, run_name="__main__"))
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
