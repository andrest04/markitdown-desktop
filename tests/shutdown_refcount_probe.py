"""How close each test module brings True to deallocation at interpreter exit.

Diagnostic for CI, not a test: Python below 3.12 aborts with "bool_dealloc" when a
C extension has dropped references to True that it did not own, and only exit shows
it. A run that drops K more references itself crashes once K passes what is left,
so bisecting K measures that margin per module. A module far below the baseline
is the one losing references. Only a crash counts as one: a child that timed out or
could not run, and a margin past the cap, are reported as not measured. Exit status
is always 0, so this never decides the CI job; the suite step does that.

    QT_QPA_PLATFORM=offscreen python tests/shutdown_refcount_probe.py
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_BASELINE = "baseline"
_MAX_DROP = 1024
_RESOLUTION = 16
_TIMEOUT_SECONDS = 300
_PYTHON_EXCEPTION_EXIT = 1  # an abort is a signal on Linux and 3 on Windows


class _NoMeasurement(Exception):
    """A child ended without saying whether it survived the drop."""


def _child(pattern: str, drop: int) -> None:
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    # Every module starts from the same imports. One that never loads Qt holds far
    # fewer references to True, and would read as the one losing them.
    from app.ui.main_window import MainWindow  # noqa: F401

    if pattern != _BASELINE:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
        with open(os.devnull, "w") as sink:
            unittest.TextTestRunner(verbosity=0, stream=sink).run(suite)
    release = ctypes.pythonapi.Py_DecRef
    release.argtypes = [ctypes.py_object]
    release.restype = None
    for _ in range(drop):
        release(True)


def _survives(pattern: str, drop: int) -> bool:
    command = [sys.executable, __file__, "--child", pattern, str(drop)]
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise _NoMeasurement(f"timed out after {_TIMEOUT_SECONDS}s at drop {drop}") from exc
    if done.returncode == _PYTHON_EXCEPTION_EXIT:
        last_line = done.stderr.decode(errors="replace").strip().splitlines()[-1:]
        raise _NoMeasurement(f"child raised at drop {drop}: {''.join(last_line)}")
    return done.returncode == 0


def _margin(pattern: str) -> str:
    try:
        return _bisect_margin(pattern)
    except Exception as exc:  # noqa: BLE001 - one module's failure must not lose the others
        return f"no measurement, {exc}"


def _bisect_margin(pattern: str) -> str:
    if not _survives(pattern, 0):
        return "crashes by itself"
    if _survives(pattern, _MAX_DROP):
        return f"above {_MAX_DROP}, not measured"
    low, high = 0, _MAX_DROP
    while high - low > _RESOLUTION:
        middle = (low + high) // 2
        if _survives(pattern, middle):
            low = middle
        else:
            high = middle
    return f"{low}..{high}"


def main() -> None:
    print(f"Python {sys.version.split()[0]}, PySide6 {version('PySide6')}, markitdown {version('markitdown')}")
    modules = sorted(path.name for path in (ROOT / "tests").glob("test_*.py"))
    patterns = [_BASELINE, *modules, "test_*.py"]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        for pattern, margin in zip(patterns, pool.map(_margin, patterns)):
            print(f"{pattern:32} {margin}", flush=True)


def run() -> None:
    """`main`, with any failure printed: this is a diagnostic, not a check."""
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - see above
        traceback.print_exc()
        print(f"Probe failed, nothing further measured: {exc}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        _child(sys.argv[2], int(sys.argv[3]))
    else:
        run()
        sys.exit(0)
