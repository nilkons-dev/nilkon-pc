"""Qt glue for the online sources: background jobs and remote thumbnails."""
import hashlib
from pathlib import Path
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

import online
from covers import image_from_bytes, square_image
from thread_bridge import Mailbox


class OnlineJobs(QObject):
    """Runs search / related / resolve / download on worker threads; results come back as signals.

    Payloads travel as plain Python objects (Signal(object)) - never converted to Qt variants.
    """
    searchDone = Signal(int, object)
    searchFailed = Signal(int, str)
    relatedDone = Signal(str, object)         # seed key, list of items
    resolved = Signal(str, str, int)          # key, direct url, duration ms
    resolveFailed = Signal(str, str)
    progress = Signal(str, float)
    finished = Signal(str, str)               # key, file path
    failed = Signal(str, str)
    cancelled = Signal(str)
    cacheDone = Signal(str, str)              # key, temporary file used for the visualiser
    cacheFailed = Signal(str)
    networkChecked = Signal(bool)
    prefetched = Signal(str, str)             # key, stream address (resolved in advance)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nilkon-online")
        self._play_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nilkon-play")     # Play never waits behind searches
        self._dl_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nilkon-download")   # downloads never block playback
        self._token = 0
        self._cancel = set()
        self._lock = threading.Lock()
        self._closed = False
        self._mb = Mailbox(self)

    def _submit(self, fn, *a):
        if self._closed:
            return
        try:
            self._pool.submit(self._guard, fn, *a)
        except RuntimeError:
            pass

    def _submit_dl(self, fn, *a):
        if self._closed:
            return
        try:
            self._dl_pool.submit(self._guard, fn, *a)
        except RuntimeError:
            pass

    @staticmethod
    def _guard(fn, *a):
        try:
            fn(*a)
        except BaseException:                  # a worker must never take the application down
            pass

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._dl_pool.shutdown(wait=False, cancel_futures=True)
        self._play_pool.shutdown(wait=False, cancel_futures=True)
        self._mb.close()

    def _emit(self, name, *args):
        """Worker-thread safe: queue the result; it is emitted from the GUI thread."""
        self._mb.post(self._deliver, name, args)

    def _deliver(self, name, args):
        if not self._closed:
            try:
                getattr(self, name).emit(*args)
            except RuntimeError:               # receiver already deleted during shutdown
                pass

    # -- search ----------------------------------------------------------------------------------
    def search(self, query):
        with self._lock:
            self._token += 1
            token = self._token
        self._submit(self._search, token, query)
        return token

    def _search(self, token, query):
        with self._lock:
            if token != self._token:           # a newer search already replaced this one
                return
        try:
            items = online.search(query)
        except Exception as exc:
            self._emit("searchFailed", token, online.friendly_error(exc))
            return
        self._emit("searchDone", token, list(items))

    def related(self, item):
        self._submit(self._related, item)

    def _related(self, item):
        try:
            items = online.related(item)
        except Exception:
            items = []
        self._emit("relatedDone", item["key"], list(items))

    # -- streaming -------------------------------------------------------------------------------
    def resolve(self, item):
        if self._closed:
            return
        try:
            self._play_pool.submit(self._guard, self._resolve, item)
        except RuntimeError:
            pass

    def check_network(self):
        self._submit(self._check_network)

    def _check_network(self):
        import socket
        ok = False
        for host in ("www.youtube.com", "www.google.com"):
            try:
                socket.create_connection((host, 443), timeout=3).close()
                ok = True
                break
            except OSError:
                continue
        self._emit("networkChecked", ok)

    def warmup(self):
        self._submit(online.warmup)

    def prefetch(self, item):
        self._submit(self._prefetch, item)

    def _prefetch(self, item):
        try:
            url, _dur = online.resolve(item)
        except Exception:
            return
        self._emit("prefetched", item["key"], url)

    def _resolve(self, item):
        try:
            url, dur = online.resolve(item)
        except Exception as exc:
            self._emit("resolveFailed", item["key"], online.friendly_error(exc))
            return
        self._emit("resolved", item["key"], url, int(dur or 0))

    def cache_audio(self, item, folder, url=""):
        """Fetch the audio into a temporary file (no tags, no conversion) so it can be analysed."""
        self._submit(self._cache, item, str(folder), url)

    def _cache(self, item, folder, url):
        key = item["key"]
        path = ""
        try:
            if url:
                path = online.fetch_audio_file(url, folder, f"{item['id']} {item['title']}", lambda: self._closed)
        except Exception:
            path = ""
        if not path:
            try:
                path = online.download(item, folder, "m4a", lambda f: None, lambda: self._closed, plain=True)
            except Exception:
                self._emit("cacheFailed", key)
                return
        self._emit("cacheDone", key, path)

    # -- downloads -------------------------------------------------------------------------------
    def download(self, item, folder, fmt):
        with self._lock:
            self._cancel.discard(item["key"])
        self._submit_dl(self._download, item, str(folder), fmt)

    def cancel(self, key):
        with self._lock:
            self._cancel.add(key)

    def _is_cancelled(self, key):
        with self._lock:
            return key in self._cancel

    def _download(self, item, folder, fmt):
        key = item["key"]
        last = [-1.0]

        def progress(frac):
            if frac - last[0] >= 0.01 or frac >= 1.0:
                last[0] = frac
                self._emit("progress", key, float(frac))
        try:
            path = online.download(item, folder, fmt, progress, lambda: self._is_cancelled(key))
        except Exception as exc:
            if self._is_cancelled(key) or isinstance(exc, online.Cancelled):
                self._emit("cancelled", key)
            else:
                self._emit("failed", key, online.friendly_error(exc))
            return
        finally:
            with self._lock:
                self._cancel.discard(key)
        self._emit("finished", key, path)


class RemoteImages(QObject):
    """Thumbnails from URLs. Fetched on worker threads (newest request first, so the pictures you are looking at
    load before old ones), kept on disk so they never load twice, small files for small pictures.
    Decoding and every Qt object stay in the GUI thread (_drain)."""
    changed = Signal()
    WORKERS = 6

    def __init__(self, parent=None, cache_dir=None):
        super().__init__(parent)
        self._mem = OrderedDict()
        self._failed = {}
        self._pending = set()
        self._done = deque()
        self._queue = deque()
        self._cv = threading.Condition()
        self._closed = False
        self._dir = Path(cache_dir) if cache_dir else Path.home() / ".nilkon_music" / "img_cache"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._dir = None
        self._workers = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        threading.Thread(target=self._trim_disk, daemon=True).start()

    def _trim_disk(self):
        """Keep the picture cache small (newest ~600 files)."""
        try:
            files = sorted(self._dir.glob("*.img"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[600:]:
                f.unlink(missing_ok=True)
        except Exception:
            pass

    def get(self, url, size=160):
        if not url:
            return None
        k = (url, size)
        pm = self._mem.get(k)
        if pm is not None:
            self._mem.move_to_end(k)
            return pm
        if k in self._pending or time.monotonic() - self._failed.get(k, -1e9) < 60:
            return None
        self._pending.add(k)
        with self._cv:
            self._queue.append(k)
            if len(self._workers) < self.WORKERS and len(self._workers) < len(self._queue) + 1:
                t = threading.Thread(target=self._loop, daemon=True, name="nilkon-img")
                self._workers.append(t)
                t.start()
            self._cv.notify()
        if not self._timer.isActive():
            self._timer.start(40)
        return None

    def reset_failed(self):
        """The connection is back: pictures that failed earlier may be tried again at once."""
        self._failed.clear()
        self.changed.emit()

    def close(self):
        self._closed = True
        with self._cv:
            self._cv.notify_all()
        self._timer.stop()

    def _loop(self):
        while True:
            with self._cv:
                while not self._queue and not self._closed:
                    self._cv.wait(5.0)
                if self._closed:
                    return
                k = self._queue.pop()                 # newest first
            self._work(k)

    def _file(self, k):
        if self._dir is None:
            return None
        return self._dir / (hashlib.sha1(f"{k[0]}|{k[1]}".encode("utf-8")).hexdigest() + ".img")

    def _work(self, k):
        """Worker thread: network / disk only."""
        data = None
        f = self._file(k)
        try:
            if f is not None and f.is_file():
                data = f.read_bytes()
                f.touch()
        except Exception:
            data = None
        if not data:
            try:
                url = online.sized(k[0], 200 if k[1] <= 200 else 544)
                data = online.fetch_bytes(url)
                if data and f is not None:
                    try:
                        f.write_bytes(data)
                    except OSError:
                        pass
            except Exception:
                data = None
        self._done.append((k, data))

    def _drain(self):
        got = False
        for _ in range(3):
            if not self._done:
                break
            k, data = self._done.popleft()
            self._pending.discard(k)
            img = None
            if data:
                try:
                    img = square_image(image_from_bytes(data), k[1])
                except Exception:
                    img = None
            if img is None:
                self._failed[k] = time.monotonic()
                continue
            self._mem[k] = QPixmap.fromImage(img)
            got = True
            while len(self._mem) > 300:
                self._mem.popitem(last=False)
        if not self._done and not self._pending:
            self._timer.stop()
        if got:
            self.changed.emit()
