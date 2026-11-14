"""Fast file download: the song is fetched in several pieces at the same time over kept-alive connections.
Pure Python, thread safe. Used for the 'Download' button (the streaming proxy has its own copy of this idea)."""
import http.client
import os
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

FIRST = 64 * 1024
START_CHUNK = 768 * 1024
MIN_CHUNK = 128 * 1024
WORKERS = 4


class FetchError(Exception):
    pass


def _ua(url):
    if "c=ANDROID_VR" in url:
        return "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
    if "c=IOS" in url:
        return "com.google.ios.youtube/19.45.4 (iPhone16,2; U; CPU iOS 18_1_0 like Mac OS X;)"
    if "c=ANDROID_MUSIC" in url:
        return "com.google.android.apps.youtube.music/7.27.52 (Linux; U; Android 11) gzip"
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36")


class _Job:
    def __init__(self, url, refresh, part, cancelled, progress, limit):
        self.url, self.refresh, self.part = url, refresh, part
        self.cancelled, self.progress, self.limit = cancelled, progress, limit
        self.size = None
        self.next = 0
        self.done_bytes = 0
        self.chunk = START_CHUNK
        self.error = None
        self.lock = threading.Lock()
        self.wlock = threading.Lock()
        self.rlock = threading.Lock()
        self.refreshed = 0.0
        self.f = None

    def fetch(self, box, start, end):
        url = self.url
        u = urlsplit(url)
        path = u.path + ("?" + u.query if u.query else "")
        hdr = {"User-Agent": _ua(url), "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        for attempt in range(2):
            c = box.get("c") if attempt == 0 and box.get("host") == u.netloc else None
            if c is None:
                cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
                c = box["c"] = cls(u.netloc, timeout=20)
                box["host"] = u.netloc
            try:
                c.request("GET", path, headers=hdr)
                r = c.getresponse()
                data = r.read()
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                    req = urllib.request.Request(r.headers["Location"], headers=hdr)
                    with urllib.request.urlopen(req, timeout=20) as r2:
                        return r2.status, r2.headers.get("Content-Range", ""), r2.read()
                if r.status >= 400:
                    raise urllib.error.HTTPError(url, r.status, r.reason, r.headers, None)
                return r.status, r.headers.get("Content-Range", ""), data
            except urllib.error.HTTPError:
                raise
            except Exception:
                try:
                    c.close()
                except Exception:
                    pass
                box.pop("c", None)
                if attempt:
                    raise
        raise OSError("request failed")

    def store(self, off, data):
        with self.wlock:
            self.f.seek(off)
            self.f.write(data)
        with self.lock:
            self.done_bytes += len(data)
            frac = self.done_bytes / float(self.size or 1)
        self.progress(min(0.99, frac))

    def renew(self):
        if not self.refresh:
            return
        with self.rlock:
            if time.monotonic() - self.refreshed < 2.0:
                return
            try:
                self.url = self.refresh() or self.url
            except Exception:
                pass
            self.refreshed = time.monotonic()

    def claim(self):
        with self.lock:
            if self.next >= self.size:
                return None
            n = min(self.chunk, self.size - self.next)
            start = self.next
            self.next += n
            return start, n

    def worker(self):
        box, fails = {}, 0
        while not self.error and not self.cancelled():
            job = self.claim()
            if job is None:
                return
            pos, stop = job[0], job[0] + job[1]
            while pos < stop and not self.error and not self.cancelled():
                m = min(stop - pos, self.chunk)
                try:
                    status, cr, data = self.fetch(box, pos, pos + m - 1)
                    if status == 200 and pos > 0:
                        data = data[pos:pos + m]
                    if len(data) < m and pos + len(data) < self.size:
                        raise OSError("short read")
                    self.store(pos, data)
                    pos += len(data)
                    fails = 0
                except urllib.error.HTTPError as exc:
                    fails += 1
                    if exc.code in (403, 404, 410):
                        if m > MIN_CHUNK:
                            self.chunk = max(MIN_CHUNK, m // 2)
                        self.renew()
                    if fails > 8:
                        self.error = f"HTTP {exc.code}"
                        return
                    time.sleep(min(2.0, 0.2 * fails))
                except Exception as exc:
                    fails += 1
                    if fails > 8:
                        self.error = str(exc)
                        return
                    time.sleep(min(3.0, 0.4 * fails))


def fetch_to_file(url, part_path, cancelled, progress, refresh=None, limit=400 << 20):
    """Downloads `url` into `part_path`. Returns the size. Raises FetchError (or Cancelled via `cancelled`)."""
    j = _Job(url, refresh, part_path, cancelled, progress, limit)
    box = {}
    last = None
    for attempt in range(5):
        if cancelled():
            raise FetchError("cancelled")
        try:
            status, cr, data = j.fetch(box, 0, FIRST - 1)
            tail = cr.rsplit("/", 1)[-1]
            total = int(tail) if tail.isdigit() else len(data) if status == 200 else None
            if not total or not data:
                raise FetchError("unknown size")
            if total > limit:
                raise FetchError("file too large")
            j.size = total
            first = data[:total]
            break
        except urllib.error.HTTPError as exc:
            last = exc
            j.renew()
            time.sleep(0.3 * (attempt + 1))
        except FetchError:
            raise
        except Exception as exc:
            last = exc
            time.sleep(0.4 * (attempt + 1))
    else:
        raise FetchError(str(last))
    with open(part_path, "wb") as f:
        j.f = f
        j.store(0, first)
        j.next = len(first)
        threads = [threading.Thread(target=j.worker, daemon=True) for _ in range(WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        f.flush()
    if cancelled():
        raise FetchError("cancelled")
    if j.error:
        raise FetchError(j.error)
    if j.done_bytes < j.size:
        raise FetchError("incomplete download")
    return j.size


def move_with_retry(src, dst, tries=12):
    """Move a finished file into place. Windows refuses while a virus scanner / the library still has the file open
    (WinError 32): wait a moment and try again, and if the target name stays blocked use a free name."""
    import shutil
    from pathlib import Path
    dst = Path(dst)
    last = None
    for i in range(tries):
        try:
            if dst.exists():
                try:
                    dst.unlink()
                except OSError:
                    pass
            shutil.move(str(src), str(dst))
            return str(dst)
        except OSError as exc:
            last = exc
            time.sleep(0.25 + 0.15 * i)
    for n in range(2, 20):
        alt = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
        if not alt.exists():
            try:
                shutil.move(str(src), str(alt))
                return str(alt)
            except OSError as exc:
                last = exc
    raise last or OSError("could not place the file")
