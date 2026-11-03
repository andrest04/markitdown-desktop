"""How close each test module brings True to deallocation at interpreter exit.

Diagnostic for CI, not a test: Python below 3.12 aborts with "bool_dealloc" when a
C extension has dropped references to True that it did not own, and only exit shows
it. A run that drops K more references itself crashes once K passes what is left,
so bisecting K measures that margin per module. A module far below the baseline
is the one losing references. Exit status is always 0; the suite step still fails.

    QT_QPA_PLATFORM=offscreen python tests/shutdown_refcount_probe.py
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_BASELINE = "baseline"
_MAX_DROP = 1024
_RESOLUTION = 16
_TIMEOUT_SECONDS = 300


def _child(pattern: str, drop: int) -> None:
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    if pattern == _BASELINE:
        from app.ui.main_window import MainWindow  # noqa: F401
    else:
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
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def _margin(pattern: str) -> str:
    if not _survives(pattern, 0):
        return "crashes by itself"
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


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        _child(sys.argv[2], int(sys.argv[3]))
    else:
        main()
