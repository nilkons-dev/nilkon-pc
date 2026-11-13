"""Discord Rich Presence ("Listening to NILKON"), Qt-free and fully threaded.

All pypresence calls happen on one worker thread, so a missing / closed Discord can never block or
crash the player.  Updates are coalesced (only the newest state is sent) and rate limited, and the
worker reconnects by itself when Discord is started later.
"""
import threading
import time

NO_ID, OFF, MISSING_LIB, WAITING, CONNECTED = "no-id", "off", "missing-lib", "waiting", "connected"
STATUS_TEXT = {
    NO_ID: "Paste your Discord Application ID to turn this on.",
    OFF: "Off",
    MISSING_LIB: "The pypresence package is not installed (pip install pypresence).",
    WAITING: "Waiting for the Discord desktop app to be open…",
    CONNECTED: "Connected - your friends can see what you are listening to.",
}


def _fit(text, fallback="Unknown"):
    """Discord needs 2..128 characters in each text field."""
    text = " ".join((text or "").split()) or fallback
    if len(text) < 2:
        text += "⠀"
    return text[:128]


def default_factory(app_id, loop):
    from pypresence import Presence
    try:
        return Presence(app_id, loop=loop)
    except TypeError:
        return Presence(app_id)


class DiscordPresence:
    def __init__(self, factory=None, min_gap=1.6, retry=12.0):
        self._factory = factory or default_factory
        self._min_gap = min_gap
        self._retry = retry
        self._cv = threading.Condition()
        self._enabled = False
        self._app_id = ""
        self._payload = None          # dict for update(), or None -> clear
        self._dirty = False
        self._stop = False
        self._thread = None
        self.status = OFF
        self.sent = 0                 # number of successful updates (diagnostics / tests)

    # -- public API (any thread) -----------------------------------------------------------------
    def configure(self, enabled, app_id):
        app_id = "".join(ch for ch in str(app_id or "") if ch.isdigit())
        with self._cv:
            changed = (bool(enabled), app_id) != (self._enabled, self._app_id)
            self._enabled, self._app_id = bool(enabled), app_id
            if not self._enabled:
                self.status = OFF
            elif not self._app_id:
                self.status = NO_ID
            elif self.status in (OFF, NO_ID):
                self.status = WAITING
            if changed:
                self._dirty = True
            self._cv.notify_all()
        if self._enabled and self._app_id:
            self._ensure_thread()

    def show(self, title, artist, album="", duration_ms=0, position_ms=0, image_url=None, now=None):
        now = time.time() if now is None else now
        start = int(now - max(0, position_ms) / 1000.0)
        payload = {
            "details": _fit(title, "Unknown song"),
            "state": _fit(artist, "Unknown artist"),
            "start": start,
            "large_image": image_url if (image_url or "").startswith("http") else "nilkon",
            "large_text": _fit(album or "NILKON music player", "NILKON"),
        }
        if duration_ms and duration_ms > 0:
            payload["end"] = start + int(duration_ms / 1000.0)
        self._set_payload(payload)

    def clear(self):
        self._set_payload(None)

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

    @property
    def status_text(self):
        return STATUS_TEXT.get(self.status, "")

    # -- internals ------------------------------------------------------------------------------------
    def _set_payload(self, payload):
        with self._cv:
            if payload == self._payload and not self._dirty:
                return
            self._payload = payload
            self._dirty = True
            self._cv.notify_all()
        if self._enabled and self._app_id:
            self._ensure_thread()

    def _ensure_thread(self):
        with self._cv:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="nilkon-discord", daemon=True)
            self._thread.start()

    @staticmethod
    def _close(rpc):
        if rpc is None:
            return
        try:
            rpc.close()
        except Exception:
            pass

    def _run(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        rpc, rpc_id = None, ""
        try:
            while True:
                with self._cv:
                    while not self._stop and not self._dirty:
                        self._cv.wait(timeout=None if not (self._enabled and self._app_id) else 30.0)
                    if self._stop:
                        break
                    enabled, app_id, payload = self._enabled, self._app_id, self._payload
                    self._dirty = False
                if not enabled or not app_id:
                    self._close(rpc)
                    rpc, rpc_id = None, ""
                    continue
                if rpc is not None and rpc_id != app_id:
                    self._close(rpc)
                    rpc = None
                if rpc is None:
                    try:
                        rpc = self._factory(app_id, loop)
                        rpc.connect()
                        rpc_id = app_id
                        self.status = CONNECTED
                    except ImportError:
                        self.status = MISSING_LIB
                        rpc = None
                        continue
                    except Exception:
                        self._close(rpc)
                        rpc = None
                        self.status = WAITING
                        self._retry_later()
                        continue
                try:
                    if payload is None:
                        rpc.clear()
                    else:
                        self._send(rpc, payload)
                    self.sent += 1
                    self.status = CONNECTED
                except Exception:
                    self._close(rpc)
                    rpc = None
                    self.status = WAITING
                    self._retry_later()
                    continue
                with self._cv:                       # rate limit; newer updates replace older ones
                    if not self._stop:
                        self._cv.wait(timeout=self._min_gap)
        finally:
            if rpc is not None:
                try:
                    rpc.clear()
                except Exception:
                    pass
                self._close(rpc)
            try:
                loop.close()
            except Exception:
                pass

    def _retry_later(self):
        """Try again in a while (Discord may simply not be running yet)."""
        def mark():
            with self._cv:
                if not self._stop and self._enabled and self._app_id:
                    self._dirty = True
                    self._cv.notify_all()
        t = threading.Timer(self._retry, mark)
        t.daemon = True
        t.start()

    @staticmethod
    def _send(rpc, payload):
        extra = {}
        try:
            from pypresence import ActivityType
            extra["activity_type"] = ActivityType.LISTENING
        except Exception:
            pass
        try:
            from pypresence import StatusDisplayType
            extra["status_display_type"] = StatusDisplayType.DETAILS
        except Exception:
            pass
        while True:
            try:
                rpc.update(**payload, **extra)
                return
            except TypeError:
                if not extra:
                    raise
                extra.popitem()          # older pypresence: drop the newest optional field and retry
