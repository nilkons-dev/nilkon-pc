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
        self.thread = threading.Thread(target=self._run, daemon=True, name="nilkon-spool")
        self.thread.start()

    # -- upstream ---------------------------------------------------------------------------------
    def _open(self, start, end):
        req = urllib.request.Request(self.url, headers={"User-Agent": self._ua(), "Range": f"bytes={start}-{end}"})
        return urllib.request.urlopen(req, timeout=15)

    def _ua(self):
        return VR_UA if "c=ANDROID_VR" in self.url else USER_AGENT

    def _run(self):
        try:
            self.f_write = open(self.path, "wb")
            fails = 0
            offline_since = None
            while not self.closed:
                start = self.have
                if self.size is not None and start >= self.size:
                    break
                if start >= min(self.limit, MAX_BYTES):
                    with self.cond:
                        self.cond.wait(0.3)
                    continue
                n = FIRST_CHUNK if start == 0 else SECOND_CHUNK if start < FIRST_CHUNK + SECOND_CHUNK else CHUNK
                try:
                    with self._open(start, start + n - 1) as r:
                        data = r.read()
                        cr = r.headers.get("Content-Range", "")
                        if self.size is None:
                            tail = cr.rsplit("/", 1)[-1]
                            if tail.isdigit():
                                self.size = int(tail)
                            elif r.status == 200:
                                self.size = len(data)
                        if r.status == 200 and start > 0:        # server ignored the range
                            data = data[start:]
                except urllib.error.HTTPError as exc:
                    fails += 1
                    if exc.code in (403, 404, 410) and self.refresh and fails <= 2:
                        try:
                            self.url = self.refresh() or self.url
                        except Exception:
                            pass
                    if fails > 4:
                        self.error = f"HTTP {exc.code}"
                        break
                    time.sleep(0.4 * fails)
                    continue
                except Exception as exc:
                    # no connection: keep trying for a while (a short outage must not stop the song)
                    if offline_since is None:
                        offline_since = time.monotonic()
                    if time.monotonic() - offline_since > OFFLINE_PATIENCE or self.closed:
                        self.error = str(exc)
                        break
                    time.sleep(min(3.0, 0.5 + 0.5 * fails))
                    fails += 1
                    continue
                offline_since = None
                if not data:
                    if self.size is None:
                        self.size = self.have
                    break
                fails = 0
                self.f_write.write(data)
                self.f_write.flush()
                with self.cond:
                    self.have += len(data)
                    self.cond.notify_all()
        except Exception as exc:
            self.error = str(exc)
        finally:
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
