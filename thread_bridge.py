"""Thread -> GUI hand-over without touching any Qt object from a worker thread.

Worker threads only append plain Python tuples to a deque; a QTimer living in the GUI
thread runs them.  (Creating or destroying PySide objects - signal instances, images - in
worker threads can crash Qt on Windows, so workers never do it.)
"""
import traceback
from collections import deque

from PySide6.QtCore import QObject, QTimer


class Mailbox(QObject):
    def __init__(self, parent=None, interval_ms=30, per_tick=40):
        super().__init__(parent)
        self._q = deque()
        self._per_tick = per_tick
        self._closed = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(interval_ms)

    def post(self, fn, *args):
        """Thread-safe. `fn(*args)` will run later in the GUI thread."""
        if not self._closed:
            self._q.append((fn, args))

    def _drain(self):
        for _ in range(self._per_tick):
            if not self._q:
                break
            fn, args = self._q.popleft()
            try:
                fn(*args)
            except Exception:
                traceback.print_exc()

    def close(self):
        self._closed = True
        self._timer.stop()
        self._q.clear()
