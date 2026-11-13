"""Cover-art thumbnails: bars trimmed, centre-filled squares, loaded on worker threads, cached on disk."""
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, QRect, Signal
from PySide6.QtGui import QImage, QPixmap, qAlpha, qBlue, qGreen, qRed

import tags

THUMB = 220
CACHE_VERSION = "v3"
_DETECT = 96          # longest side used when looking for letterbox bars
_TOL = 20             # max colour spread (0-255) for a row/column to count as a flat bar


def _flat(values):
    """True when a row/column of ARGB ints is one flat colour (or transparent)."""
    if all(qAlpha(v) < 24 for v in values):
        return True
    if any(qAlpha(v) < 24 for v in values):
        return False
    for ch in (qRed, qGreen, qBlue):
        vs = [ch(v) for v in values]
        if max(vs) - min(vs) > _TOL:
            return False
    return True


def trim_bars(img):
    """Crop flat/transparent letterbox bars so the real picture can fill a rounded square."""
    if img.isNull() or img.width() < 16 or img.height() < 16:
        return img
    small = img.scaled(_DETECT, _DETECT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    small = small.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = small.width(), small.height()
    if w < 8 or h < 8:
        return img
    rows = lambda y: [small.pixel(x, y) for x in range(w)]
    cols = lambda x: [small.pixel(x, y) for y in range(h)]
    top = 0
    while top < h // 2 and _flat(rows(top)):
        top += 1
    bottom = h
    while bottom > h // 2 + 1 and _flat(rows(bottom - 1)):
        bottom -= 1
    left = 0
    while left < w // 2 and _flat(cols(left)):
        left += 1
    right = w
    while right > w // 2 + 1 and _flat(cols(right - 1)):
        right -= 1
    if top == 0 and left == 0 and bottom == h and right == w:
        return img
    sx, sy = img.width() / float(w), img.height() / float(h)
    # one extra pixel inwards hides anti-aliased bar edges
    x0 = int(left * sx) + (1 if left else 0)
    y0 = int(top * sy) + (1 if top else 0)
    x1 = int(right * sx) - (1 if right != w else 0)
    y1 = int(bottom * sy) - (1 if bottom != h else 0)
    if x1 - x0 < img.width() * 0.3 or y1 - y0 < img.height() * 0.3:
        return img
    return img.copy(QRect(x0, y0, x1 - x0, y1 - y0))


def square_image(img, size):
    """Trim bars, centre-crop to a square and scale to size x size (smooth)."""
    if img is None or img.isNull():
        return None
    img = trim_bars(img)
    s = min(img.width(), img.height())
    if s <= 0:
        return None
    sq = img.copy(QRect((img.width() - s) // 2, (img.height() - s) // 2, s, s))
    return sq.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def image_from_bytes(data):
    if not data:
        return None
    img = QImage()
    if img.loadFromData(data) and not img.isNull():
        return img
    return None


def square_pixmap(pm, size):
    """Pixmap flavour of square_image (GUI thread)."""
    if pm is None or pm.isNull():
        return None
    out = square_image(pm.toImage(), size)
    return None if out is None else QPixmap.fromImage(out)


def pixmap_from_bytes(data):
    img = image_from_bytes(data)
    return None if img is None else QPixmap.fromImage(img)


class CoverCache(QObject):
    """get(path) returns a thumbnail at once if known, otherwise loads it in the background
    and emits `changed` when new thumbnails arrived."""
    changed = Signal()

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self.dir = Path(cache_dir) / "covers"
        self._mem = {}
        self._missing = set()
        self._pending = set()
        self._done = deque()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nilkon-cover")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)

    def get(self, path):
        pm = self._mem.get(path)
        if pm is not None:
            return pm
        if path not in self._missing and path not in self._pending:
            self._pending.add(path)
            try:
                self._pool.submit(self._work, path)
            except RuntimeError:        # pool already shut down
                self._pending.discard(path)
                return None
            if not self._timer.isActive():
                self._timer.start(40)
        return None

    def set_override(self, path, pm):
        if pm is not None and not pm.isNull():
            self._mem[path] = pm

    def forget(self, path):
        self._mem.pop(path, None)
        self._missing.discard(path)

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._timer.stop()

    # -- worker side (no QPixmap here) ---------------------------------------------------
    def _disk_file(self, path):
        try:
            st = Path(path).stat()
            key = f"{zlib.crc32(path.encode('utf-8', 'ignore')):08x}_{st.st_size}_{int(st.st_mtime)}_{THUMB}_{CACHE_VERSION}.png"
        except OSError:
            return None
        return self.dir / key

    def _work(self, path):
        """Worker thread: file access only (no Qt objects). Images are decoded in the GUI thread."""
        res = (None, None)
        try:
            f = self._disk_file(path)
            if f is not None and f.is_file():
                res = ("cached", f.read_bytes())
            else:
                raw = tags.read_cover(path)
                res = ("raw", raw) if raw else (None, None)
        except Exception:
            res = (None, None)
        self._done.append((path, res[0], res[1]))

    # -- GUI side ----------------------------------------------------------------------------
    def _drain(self):
        loaded = False
        for _ in range(4):
            if not self._done:
                break
            path, kind, data = self._done.popleft()
            self._pending.discard(path)
            img = None
            try:
                if kind == "cached":
                    img = image_from_bytes(data)
                elif kind == "raw":
                    img = square_image(image_from_bytes(data), THUMB)
                    f = self._disk_file(path)
                    if img is not None and f is not None:
                        try:
                            self.dir.mkdir(parents=True, exist_ok=True)
                            img.save(str(f), "PNG")
                        except Exception:
                            pass
            except Exception:
                img = None
            if img is not None:
                self._mem[path] = QPixmap.fromImage(img)
                loaded = True
            else:
                self._missing.add(path)
        if not self._done and not self._pending:
            self._timer.stop()
        if loaded:
            self.changed.emit()
