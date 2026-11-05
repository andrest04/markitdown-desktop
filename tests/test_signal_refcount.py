"""Emitting a signal must not cost a reference to `True`.

PySide6 6.12.0 loses one on every `Signal.emit()` called from Python, with no
receiver and whatever the signal type. On Linux with Python 3.11 `True` eventually
reaches deallocation and the process aborts with `Fatal Python error: bool_dealloc`.
requirements.txt holds PySide6 below 6.12 because of it. This test is what says
whether a later release can lift that.
"""
from __future__ import annotations

import gc
import sys
import unittest

from PySide6.QtCore import QObject, Signal
from qt_support import qapp

_EMITS = 100
# Far below _EMITS, so a loss of one reference per emit fails clearly.
_NOISE_MARGIN = 10


class _Emitter(QObject):
    with_bool = Signal(bool)
    without_args = Signal()


def _references_lost(emit) -> int:
    gc.collect()
    before = sys.getrefcount(True)
    for _ in range(_EMITS):
        emit()
    gc.collect()
    return before - sys.getrefcount(True)


@unittest.skipUnless(
    sys.version_info < (3, 12),
    "Python 3.12+ has immortal booleans, so their reference count cannot show the loss",
)
class SignalRefcountTests(unittest.TestCase):
    def setUp(self):
        qapp()
        self.emitter = _Emitter()

    def assert_keeps_references(self, emit):
        lost = _references_lost(emit)
        self.assertLessEqual(
            lost, _NOISE_MARGIN, f"True lost {lost} references over {_EMITS} emits"
        )

    def test_bool_signal_with_no_receiver(self):
        self.assert_keeps_references(lambda: self.emitter.with_bool.emit(True))

    def test_argless_signal_with_no_receiver(self):
        self.assert_keeps_references(self.emitter.without_args.emit)


if __name__ == "__main__":
    unittest.main()
