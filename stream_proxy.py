"""Local streaming proxy: one download per song, shared by the player and the sound-wave analysis.

Why: playing a stream directly makes the player wait for the network at every hiccup, and the wave analysis would
need a second download. Here a background thread fetches the song from the internet as fast as the connection
allows (ahead of the playback position) into a temporary file, and the player / analyser read it from
http://127.0.0.1 - so playback starts as soon as the first bytes arrive, never stalls while the download is ahead,
and seeking works. Pure Python (no Qt objects), safe to use from any thread.
"""
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
VR_UA = "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
FIRST_CHUNK = 64 * 1024           # small first request: playback can start at once, even on a slow line
SECOND_CHUNK = 320 * 1024
CHUNK = 1024 * 1024
MIN_CHUNK = 128 * 1024
START_CHUNK = 512 * 1024          # size of the pieces the parallel workers fetch (shrinks if the server refuses big ones)
WORKERS = 3
MAX_BYTES = 80 * 1024 * 1024
OFFLINE_PATIENCE = 75.0           # seconds without internet before a song gives up
PREFETCH_BYTES = 1536 * 1024
SEEK_AHEAD = 3 * 1024 * 1024      # a request further ahead than this is served straight from the internet


class Session:
    def __init__(self, key, url, folder, refresh=None, limit=MAX_BYTES):
        self.limit = limit                # a prefetched song only downloads its first part until it is played
        self.key = key
        self.url = url
        self.refresh = refresh            # () -> new upstream url, used when the address expired
        self.size = None
        self.have = 0
        self.closed = False
        self.error = None
        self.cond = threading.Condition()
        self.path = Path(folder) / (re.sub(r"[^A-Za-z0-9_-]", "_", key)[:60] + "-" + str(int(time.time() * 1000)) + ".spool")
        self.mime = (re.search(r"[?&]mime=([^&]+)", url) or [None, "audio%2Fmp4"])[1].replace("%2F", "/")
        self.ext = ".webm" if "webm" in self.mime else ".m4a"
        self.f_write = None
        self._wlock = threading.Lock()
        self._clock = threading.Lock()
        self._rlock = threading.Lock()
        self._refreshed = 0.0
        self._parts = {}
        self._next = 0
        self.chunk = START_CHUNK
        self.thread = threading.Thread(target=self._run, daemon=True, name="nilkon-spool")
        self.thread.start()

    # -- upstream ---------------------------------------------------------------------------------
    def _open(self, start, end):
        req = urllib.request.Request(self.url, headers={"User-Agent": self._ua(), "Range": f"bytes={start}-{end}"})
        return urllib.request.urlopen(req, timeout=15)

    def _ua(self):
        if "c=ANDROID_VR" in self.url:
            return VR_UA
        if "c=IOS" in self.url:
            return "com.google.ios.youtube/19.45.4 (iPhone16,2; U; CPU iOS 18_1_0 like Mac OS X;)"
        if "c=ANDROID_MUSIC" in self.url:
            return "com.google.android.apps.youtube.music/7.27.52 (Linux; U; Android 11) gzip"
        return USER_AGENT

    # -- parallel downloader ------------------------------------------------------------------------
    def _fetch(self, conn_box, start, end):
        """One ranged request over a kept-alive connection (no new TLS handshake per chunk)."""
        import http.client
        from urllib.parse import urlsplit
        url = self.url
        u = urlsplit(url)
        path = u.path + ("?" + u.query if u.query else "")
        hdr = {"User-Agent": self._ua(), "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        for attempt in range(2):
            c = conn_box.get("c") if attempt == 0 and conn_box.get("host") == u.netloc else None
            if c is None:
                cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
                c = conn_box["c"] = cls(u.netloc, timeout=15)
                conn_box["host"] = u.netloc
            try:
                c.request("GET", path, headers=hdr)
                r = c.getresponse()
                data = r.read()
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                    req = urllib.request.Request(r.headers["Location"], headers=hdr)
                    with urllib.request.urlopen(req, timeout=15) as r2:
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
                conn_box.pop("c", None)
                if attempt:
                    raise
        raise OSError("request failed")

    def _store(self, off, data):
        with self._wlock:
            self.f_write.seek(off)
            self.f_write.write(data)
            self.f_write.flush()
        with self.cond:
            self._parts[off] = len(data)
            while self.have in self._parts:
                self.have += self._parts.pop(self.have)
            self.cond.notify_all()

    def _claim(self):
        """Next piece of the song for a worker: (offset, length), or None when everything is taken."""
        with self._clock:
            start = self._next
            top = min(self.size or 0, self.limit, MAX_BYTES)
            if start >= top:
                return None
            n = min(self.chunk, top - start)
            self._next = start + n
            return start, n

    def _worker(self):
        box = {}
        fails = 0
        offline_since = None
        while not self.closed and not self.error:
            if self._wait_limit():
                continue
            job = self._claim()
            if job is None:
                if self._all_claimed():
                    return
                with self.cond:
                    self.cond.wait(0.3)
                continue
            start, n = job
            pos, stop = start, start + n
            while pos < stop and not self.closed and not self.error:
                m = min(stop - pos, self.chunk)                 # the piece may shrink if the server refuses big ones
                try:
                    status, cr, data = self._fetch(box, pos, pos + m - 1)
                    if status == 200 and pos > 0:               # the server ignored the range
                        data = data[pos:pos + m]
                    if len(data) < m and pos + len(data) < (self.size or 0):
                        raise OSError("short read")
                    self._store(pos, data)
                    pos += len(data)
                    fails = 0
                    offline_since = None
                except urllib.error.HTTPError as exc:
                    fails += 1
                    if exc.code in (403, 404, 410):
                        if m > MIN_CHUNK:
                            self.chunk = max(MIN_CHUNK, m // 2)
                        self._refresh_url()
                    if fails > 8:
                        self.error = f"HTTP {exc.code}"
                        return
                    time.sleep(min(2.0, 0.2 * fails))
                except Exception as exc:
                    # no connection: keep trying for a while (a short outage must not stop the song)
                    if offline_since is None:
                        offline_since = time.monotonic()
                    if time.monotonic() - offline_since > OFFLINE_PATIENCE or self.closed:
                        self.error = str(exc)
                        return
                    fails += 1
                    time.sleep(min(3.0, 0.4 + 0.4 * fails))

    def _refresh_url(self):
        if not self.refresh:
            return
        with self._rlock:
            if time.monotonic() - self._refreshed < 2.0:
                return                                      # another worker has just done it
            try:
                self.url = self.refresh() or self.url
            except Exception:
                pass
            self._refreshed = time.monotonic()

    def _wait_limit(self):
        """A prefetched song only downloads its first part until it is played."""
        if self._next >= min(self.limit, MAX_BYTES) and not (self.size is not None and self._next >= self.size):
            with self.cond:
                self.cond.wait(0.3)
            return True
        return False

    def _all_claimed(self):
        return self.size is not None and self._next >= self.size

    def _run(self):
        workers = []
        try:
            self.f_write = open(self.path, "wb")
            fails = 0
            offline_since = None
            box = {}
            while self.size is None and not self.closed:        # first small piece: gives the song size, playback starts
                try:
                    status, cr, data = self._fetch(box, 0, FIRST_CHUNK - 1)
                except urllib.error.HTTPError as exc:
                    fails += 1
                    if exc.code in (403, 404, 410):
                        self._refresh_url()
                    if fails > 5:
                        self.error = f"HTTP {exc.code}"
                        return
                    time.sleep(0.3 * fails)
                    continue
                except Exception as exc:
                    if offline_since is None:
                        offline_since = time.monotonic()
                    if time.monotonic() - offline_since > OFFLINE_PATIENCE:
                        self.error = str(exc)
                        return
                    fails += 1
                    time.sleep(min(3.0, 0.5 + 0.5 * fails))
                    continue
                tail = cr.rsplit("/", 1)[-1]
                total = int(tail) if tail.isdigit() else len(data) if status == 200 else None
                if status == 200:
                    data = data[:total] if total else data
                if total is None or not data:
                    self.error = "unknown size"
                    return
                self._store(0, data)
                with self.cond:
                    self._next = len(data)
                    self.size = total
                    self.cond.notify_all()
            for i in range(WORKERS):
                t = threading.Thread(target=self._worker, daemon=True, name=f"nilkon-spool-{i}")
                t.start()
                workers.append(t)
            for t in workers:
                while t.is_alive() and not self.closed:
                    t.join(0.3)
        except Exception as exc:
            self.error = str(exc)
        finally:
            for t in workers:
                t.join(timeout=2)
            with self.cond:
                if self.size is None:
                    self.size = self.have
                self.cond.notify_all()
            try:
                if self.f_write:
                    self.f_write.close()
            except Exception:
                pass

    def wait_size(self, timeout=15.0):
        end = time.monotonic() + timeout
        with self.cond:
            while self.size is None and not self.error and not self.closed and time.monotonic() < end:
                self.cond.wait(0.2)
        return self.size

    def wait_have(self, pos, timeout=15.0):
        """Block until byte `pos` is on disk. Returns bytes available (0 on timeout / failure)."""
        end = time.monotonic() + timeout
        with self.cond:
            while self.have <= pos and not self.closed and not self.error and time.monotonic() < end:
                if self.size is not None and pos >= self.size:
                    break
                self.cond.wait(0.2)
            return self.have

    def close(self):
        self.closed = True
        with self.cond:
            self.cond.notify_all()
        threading.Thread(target=self._cleanup, daemon=True).start()

    def _cleanup(self):
        self.thread.join(timeout=6)
        for _ in range(5):
            try:
                os.remove(self.path)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(1.0)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hub = None

    def log_message(self, *a):
        pass

    def _session(self):
        m = re.match(r"^/s/([^/.]+)", self.path)
        return self.hub.sessions.get(m.group(1)) if m else None

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        try:
            s = self._session()
            if s is None:
                self.send_error(404)
                return
            size = s.wait_size()
            if not size:
                self.send_error(502)
                return
            start, end = 0, size - 1
            rng = self.headers.get("Range", "")
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            partial = False
            if m and (m.group(1) or m.group(2)):
                partial = True
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:                                   # suffix range: last N bytes
                    start = max(0, size - int(m.group(2)))
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", s.mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            pos = start
            if pos > s.have + SEEK_AHEAD and not s.closed:
                self._passthrough(s, pos, end)
                return
            with open(s.path, "rb") as f:
                while pos <= end:
                    waited = 0.0
                    have = s.wait_have(pos)
                    while have <= pos and not s.closed and not s.error and waited < OFFLINE_PATIENCE + 10:
                        waited += 15.0                      # the download is retrying (no internet): keep the player waiting
                        have = s.wait_have(pos)
                    if have <= pos:
                        break
                    n = min(64 * 1024, have - pos, end - pos + 1)
                    f.seek(pos)
                    buf = f.read(n)
                    if not buf:
                        break
                    self.wfile.write(buf)
                    pos += len(buf)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        except Exception:
            pass

    def _passthrough(self, s, pos, end):
        """Seek far ahead of the download: stream that part straight from the internet."""
        try:
            req = urllib.request.Request(s.url, headers={"User-Agent": s._ua(), "Range": f"bytes={pos}-{end}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                while True:
                    buf = r.read(64 * 1024)
                    if not buf:
                        break
                    self.wfile.write(buf)
        except Exception:
            pass


class StreamHub:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.sessions = {}
        self._lock = threading.Lock()
        self._server = None
        self.port = 0
        self.current = None

    def _ensure_server(self):
        if self._server is not None:
            return
        handler = type("Handler", (_Handler,), {"hub": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True, name="nilkon-proxy").start()

    def start(self, key, url, refresh=None, prefetch=False):
        """Begin fetching `url`; returns the local address the player should open.
        prefetch=True only downloads the first part of the song (so the next song starts at once);
        starting the same key normally continues that download instead of starting over."""
        self.folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._ensure_server()
            sid = re.sub(r"[^A-Za-z0-9_-]", "_", key)[:60]
            s = self.sessions.get(sid)
            if s is not None and (s.closed or s.error or (s.size is not None and s.have == 0)):
                self.sessions.pop(sid).close()
                s = None
            if s is None:
                s = Session(key, url, self.folder, refresh, limit=PREFETCH_BYTES if prefetch else MAX_BYTES)
                self.sessions[sid] = s
            elif not prefetch:
                s.limit = MAX_BYTES
                with s.cond:
                    s.cond.notify_all()
            if not prefetch:
                self.current = sid
            for k in list(self.sessions):                 # keep the playing song and at most one prefetched song
                if k != sid and k != self.current and len(self.sessions) > 2:
                    self.sessions.pop(k).close()
                elif k != sid and k != self.current and self.sessions[k].limit >= MAX_BYTES:
                    self.sessions.pop(k).close()          # an older fully-fetching song nobody listens to
        return f"http://127.0.0.1:{self.port}/s/{sid}{s.ext}"

    def close_all(self):
        with self._lock:
            for s in self.sessions.values():
                s.close()
            self.sessions.clear()
            if self._server is not None:
                try:
                    self._server.shutdown()
                except Exception:
                    pass
                self._server = None

    def sweep(self):
        """Remove leftover spool files of earlier runs."""
        try:
            for f in self.folder.glob("*.spool"):
                try:
                    f.unlink()
                except OSError:
                    pass
        except OSError:
            pass
