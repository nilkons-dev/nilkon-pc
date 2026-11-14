"""Online music (Qt-free): song search, related songs, stream-URL resolving and downloading.

Search and "related songs" talk to the public music catalogue directly (fast, songs only);
resolving a playable URL and downloading use the free `yt-dlp` package.
Every function here blocks, so the GUI always calls them from a worker thread.
"""
import glob
import json
import threading
import time
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
MUSIC_API = "https://music.youtube.com/youtubei/v1"
CLIENT_VERSION = "1.20250310.01.00"
SONGS_FILTER = "EgWKAQIIAWoMEA4QChADEAQQCRAF"      # "Songs" filter of the catalogue search
AUDIO_GLOBS = ("*.mp3", "*.m4a", "*.opus", "*.webm", "*.ogg", "*.flac", "*.wav", "*.aac")
CHUNK = 64 * 1024


class OnlineError(Exception):
    """An error whose message is safe to show to the user as it is."""


class Cancelled(Exception):
    pass


# -- helpers -----------------------------------------------------------------------------------------
def make_key(provider, vid):
    return f"online:{provider}:{vid}"


def make_item(provider, vid, title, artist, duration_ms, thumb_url, page_url, cover_url=""):
    return {"key": make_key(provider, vid), "provider": provider, "id": str(vid),
            "title": (title or "Unknown title").strip(), "artist": (artist or "").strip(),
            "duration_ms": int(duration_ms or 0), "thumb_url": thumb_url or "", "page_url": page_url or "",
            "cover_url": cover_url or thumb_url or ""}


def safe_name(text, limit=110):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip(" .")
    return (text or "song")[:limit].rstrip(" .")


def friendly_error(exc):
    """Turn library / network exceptions into one short sentence."""
    if isinstance(exc, OnlineError):
        return str(exc)
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return "Too many requests. Wait a minute and try again."
        return f"The music service answered with an error ({exc.code}). Try again in a moment."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)) or any(
            k in low for k in ("getaddrinfo", "name or service", "timed out", "timeout", "network is unreachable",
                               "failed to resolve", "connection reset", "temporary failure", "no route to host")):
        return "No internet connection. Check your network and try again."
    if "sign in to confirm" in low or "not a bot" in low:
        return "The music service asked for verification. Wait a little and try again, or choose your browser in Settings → Online."
    if "429" in low or "too many requests" in low:
        return "Too many requests. Wait a minute and try again."
    if "unavailable" in low or "private video" in low or "not available" in low:
        return "This video is not available."
    if "unsupported url" in low:
        return "This link is not supported."
    first = re.sub(r"\x1b\[[0-9;]*m", "", msg).strip().splitlines()[0] if msg.strip() else exc.__class__.__name__
    return first[:200]


def fetch_bytes(url, timeout=15, limit=8 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def find_ffmpeg():
    """Path of an ffmpeg executable (pip `imageio-ffmpeg`, bundled next to the app, or on PATH) or None."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = Path(base) / name
            if p.is_file():
                return str(p)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def tag_file(path, title, artist, cover_jpeg=None):
    """Best-effort tags + cover art with mutagen (silently skipped when unavailable)."""
    try:
        ext = Path(path).suffix.lower()
        if ext == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, APIC
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.setall("TIT2", [TIT2(encoding=3, text=title)])
            if artist:
                tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
            if cover_jpeg and not tags.getall("APIC"):
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_jpeg))
            tags.save(path)
        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4, MP4Cover
            f = MP4(path)
            f["\xa9nam"] = [title]
            if artist:
                f["\xa9ART"] = [artist]
            if cover_jpeg and "covr" not in f:
                f["covr"] = [MP4Cover(cover_jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
            f.save()
    except Exception:
        pass


# -- catalogue (search / related) --------------------------------------------------------------------------
_BULLETS = {"•", "·", "\u2022"}
_TYPE_WORDS = {"song", "video", "single", "ep", "album", "playlist", "artist", "podcast", "episode"}
_DUR_RE = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")


_tls = threading.local()


def _conn(fresh=False):
    """One kept-alive HTTPS connection per thread: a search no longer pays the connection set-up each time."""
    import http.client
    c = getattr(_tls, "conn", None)
    if c is None or fresh:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        host = urllib.parse.urlparse(MUSIC_API).hostname
        c = http.client.HTTPSConnection(host, timeout=10)
        _tls.conn = c
    return c


def _post_json(endpoint, body, timeout=8):
    import gzip
    body = dict(body)
    body["context"] = {"client": {"clientName": "WEB_REMIX", "clientVersion": CLIENT_VERSION, "hl": "en", "gl": "US"}}
    payload = json.dumps(body).encode("utf-8")
    path = urllib.parse.urlparse(MUSIC_API).path + f"/{endpoint}?prettyPrint=false"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept-Language": "en-US,en;q=0.9",
               "Accept-Encoding": "gzip", "Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"}
    last = None
    for attempt in range(2):                      # a kept-alive connection may have been closed by the server
        c = _conn(fresh=attempt > 0)
        try:
            c.timeout = timeout
            c.request("POST", path, payload, headers)
            resp = c.getresponse()
            raw = resp.read()
            if resp.status >= 400:
                raise urllib.error.HTTPError(MUSIC_API, resp.status, resp.reason, resp.headers, None)
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            last = exc
            try:
                c.close()
            except Exception:
                pass
            _tls.conn = None
    raise last


def _walk(obj, key):
    """Yield every value stored under `key` anywhere inside obj, in document order."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            kids = []
            for k, v in cur.items():
                if k == key:
                    kids.append((True, v))
                elif isinstance(v, (dict, list)):
                    kids.append((False, v))
            for hit, v in reversed(kids):
                if hit:
                    stack.append(_Hit(v))
                else:
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(reversed([x for x in cur if isinstance(x, (dict, list, _Hit))]))
        elif isinstance(cur, _Hit):
            yield cur.value
            if isinstance(cur.value, (dict, list)):
                stack.append(cur.value)


class _Hit:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def _first(obj, key, default=None):
    for v in _walk(obj, key):
        return v
    return default


def _runs_text(node):
    runs = (node or {}).get("runs") if isinstance(node, dict) else None
    return [str(r.get("text", "")) for r in runs or [] if isinstance(r, dict)]


def _groups(texts):
    """['A',' & ','B',' • ','Album',' • ','3:45'] -> ['A & B','Album','3:45']"""
    out, cur = [], []
    for t in texts:
        if t.strip() in _BULLETS:
            if cur:
                out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append("".join(cur).strip())
    return [g for g in out if g]


def _dur_ms(text):
    if not text or not _DUR_RE.match(text.strip()):
        return 0
    secs = 0
    for part in text.strip().split(":"):
        secs = secs * 60 + int(part)
    return secs * 1000


def _thumbs(node):
    ths = _first(node, "thumbnails") or []
    urls = [t.get("url") for t in ths if isinstance(t, dict) and t.get("url")]
    return urls[0] if urls else "", urls[-1] if urls else ""


def sized(url, size):
    return _sized(url, size)


def _sized(url, size):
    """Re-size a googleusercontent artwork URL (…=w60-h60-l90-rj)."""
    if not url:
        return ""
    if "googleusercontent.com" in url or "ggpht.com" in url:
        if "=" in url:
            return re.sub(r"=[wsh]\d+.*$", f"=w{size}-h{size}-l90-rj", url)
    return url


def _item_from(vid, title, groups, thumb_small, thumb_big):
    artist, dur = "", 0
    rest = []
    for g in groups:
        if _dur_ms(g):
            dur = _dur_ms(g)
        elif g.lower() in _TYPE_WORDS:
            continue
        else:
            rest.append(g)
    if rest:
        artist = rest[0]
    thumb = _sized(thumb_small, 226) or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
    cover = _sized(thumb_big or thumb_small, 544) or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    return make_item("youtube", vid, title, artist, dur, thumb, f"https://music.youtube.com/watch?v={vid}", cover)


def parse_search(data, limit=25):
    out, seen = [], set()
    for r in _walk(data, "musicResponsiveListItemRenderer"):
        if not isinstance(r, dict):
            continue
        cols = r.get("flexColumns") or []
        if len(cols) < 2:
            continue
        def col(i):
            return _runs_text(_first(cols[i], "text"))
        title_runs = col(0)
        vid = (r.get("playlistItemData") or {}).get("videoId") or _first(r, "videoId")
        if not vid or not title_runs or vid in seen:
            continue
        seen.add(vid)
        s, b = _thumbs(r.get("thumbnail") or {})
        out.append(_item_from(vid, "".join(title_runs).strip(), _groups(col(1)), s, b))
        if len(out) >= limit:
            break
    return out


def parse_related(data, limit=30):
    out, seen = [], set()
    for r in _walk(data, "playlistPanelVideoRenderer"):
        if not isinstance(r, dict) or not r.get("videoId") or r["videoId"] in seen:
            continue
        seen.add(r["videoId"])
        title = "".join(_runs_text(r.get("title"))).strip()
        groups = _groups(_runs_text(r.get("longBylineText")) or _runs_text(r.get("shortBylineText")))
        length = "".join(_runs_text(r.get("lengthText"))) or (r.get("lengthText") or {}).get("simpleText", "")
        if length:
            groups.append(length)
        s, b = _thumbs(r.get("thumbnail") or {})
        if title:
            out.append(_item_from(r["videoId"], title, groups, s, b))
        if len(out) >= limit:
            break
    return out


def _fallback_search(query, limit):
    yt = _ytdlp()
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
            "noplaylist": True, "socket_timeout": 15, "logger": _Quiet()}
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{int(limit) + 10}:{query}", download=False)
    out = []
    for e in (info or {}).get("entries") or []:
        if not e or not e.get("id") or e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        dur = int((e.get("duration") or 0) * 1000)
        if dur and not (60_000 <= dur <= 15 * 60_000):      # skip clips and long mixes / podcasts
            continue
        vid = e["id"]
        artist = re.sub(r"\s*-\s*Topic$", "", e.get("channel") or e.get("uploader") or "")
        out.append(make_item("youtube", vid, e.get("title"), artist, dur, f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                             f"https://music.youtube.com/watch?v={vid}", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"))
        if len(out) >= limit:
            break
    return out


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id_from_url(text):
    """11-character video id of a pasted link (watch, youtu.be, shorts, embed, music...), else ''."""
    t = (text or "").strip()
    if not re.match(r"^(https?://|www\.|m\.|music\.|youtu)", t, re.I):
        return ""
    if not t.lower().startswith("http"):
        t = "https://" + t
    try:
        u = urllib.parse.urlparse(t)
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    if not (host.endswith("youtube.com") or host.endswith("youtu.be") or host.endswith("youtube-nocookie.com")):
        return ""
    q = urllib.parse.parse_qs(u.query)
    cand = (q.get("v") or [""])[0]
    if not cand:
        parts = [p for p in u.path.split("/") if p]
        if host.endswith("youtu.be") and parts:
            cand = parts[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v", "e"):
            cand = parts[1]
    return cand if _ID_RE.match(cand or "") else ""


def lookup_url(text):
    """A pasted link -> one song item (so any song can be found by its link)."""
    vid = video_id_from_url(text)
    if not vid:
        raise OnlineError("This link is not a supported song link.")
    page = "https://music.youtube.com/watch?v=" + vid
    thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
    big = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    info = None
    try:
        yt = _ytdlp()

        def run(opts):
            with yt.YoutubeDL(opts) as ydl:
                return ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
        info = _with_clients({"skip_download": True, "socket_timeout": 12}, run, fast=False)
    except Exception:
        info = None
    if info and info.get("title"):
        if info.get("live_status") in ("is_live", "is_upcoming"):
            raise OnlineError("Live streams cannot be played here.")
        artist = info.get("artist") or info.get("creator") or info.get("channel") or info.get("uploader") or ""
        artist = re.sub(r"\s*-\s*Topic$", "", str(artist).split(",")[0] if info.get("artist") else str(artist))
        title = info.get("track") or info["title"]
        return make_item("youtube", vid, title, artist, int((info.get("duration") or 0) * 1000), thumb, page, big)
    try:                                                    # lighter fallback: the public oEmbed record
        raw = fetch_bytes("https://www.youtube.com/oembed?format=json&url=" +
                          urllib.parse.quote("https://www.youtube.com/watch?v=" + vid, safe=""), timeout=10)
        d = json.loads(raw.decode("utf-8", "replace"))
        return make_item("youtube", vid, d.get("title"), re.sub(r"\s*-\s*Topic$", "", d.get("author_name", "")),
                         0, thumb, page, big)
    except Exception as exc:
        raise OnlineError("Could not open this link. " + friendly_error(exc)) from exc


def search(query, limit=25):
    """Songs matching `query` (music tracks only, no random videos). A pasted song link returns that song."""
    query = (query or "").strip()
    if not query:
        return []
    if video_id_from_url(query):
        return [lookup_url(query)]
    err = None
    try:
        items = parse_search(_post_json("search", {"query": query, "params": SONGS_FILTER}), limit)
        if items:
            return items
    except Exception as exc:
        err = exc
    try:
        return _fallback_search(query, limit)
    except Exception as exc:
        raise OnlineError(friendly_error(err or exc)) from exc


def related(item, limit=30):
    """Songs that play well after `item` (like an automatic radio)."""
    vid = item["id"]
    try:
        items = parse_related(_post_json("next", {
            "videoId": vid, "playlistId": "RDAMVM" + vid, "params": "wAEB",
            "isAudioOnly": True, "enablePersistentPlaylistPanel": True,
            "tunerSettingValue": "AUTOMIX_SETTING_NORMAL"}), limit + 1)
        items = [i for i in items if i["id"] != vid]
        if items:
            return items[:limit]
    except Exception:
        pass
    if item.get("artist"):                                   # fall back to more songs by the same artist
        try:
            return [i for i in search(item["artist"], limit + 1) if i["id"] != vid][:limit]
        except OnlineError:
            pass
    return []


# -- stream URL + download (yt-dlp) ------------------------------------------------------------------------
def _ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        raise OnlineError("Online music needs the free 'yt-dlp' package. "
                          "Run Run_NILKON.bat again or install it with:  py -m pip install yt-dlp")


def _watch_url(item):
    return "https://www.youtube.com/watch?v=" + item["id"]


_resolve_cache = {}
_resolve_lock = threading.Lock()
_fast_ok = [True]
RESOLVE_TTL = 20 * 60


class _Quiet:
    """yt-dlp logger that prints nothing (the app shows its own friendly messages instead of console errors)."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


COOKIE_BROWSER = [""]            # "", "chrome", "edge", "firefox", "brave" ... (set from Settings)
_CLIENTS = (None, ("android_vr",), ("tv",), ("web_safari",), ("mweb",), ("ios",))
_good_client = [0]
_RETRY_WORDS = ("sign in", "bot", "not available", "requested format", "403", "po token", "forbidden",
                "unable to extract", "player response", "no video formats")


def _client_opts(base, idx, fast=False):
    opts = dict(base)
    opts.update({"quiet": True, "no_warnings": True, "logger": _Quiet(), "noplaylist": True})
    yt_args = {}
    if _CLIENTS[idx]:
        yt_args["player_client"] = list(_CLIENTS[idx])
    if fast:
        yt_args["player_skip"] = ["webpage", "configs"]
    if yt_args:
        opts["extractor_args"] = {"youtube": yt_args}
    if COOKIE_BROWSER[0]:
        opts["cookiesfrombrowser"] = (COOKIE_BROWSER[0],)
    return opts


def _with_clients(base, run, fast=False):
    """Run `run(opts)` trying the known-good YouTube client first, then the others, when one is refused
    (for example by the 'sign in to confirm you are not a bot' check)."""
    order = [_good_client[0]] + [i for i in range(len(_CLIENTS)) if i != _good_client[0]]
    last = None
    for idx in order:
        try:
            out = run(_client_opts(base, idx, fast))
            _good_client[0] = idx
            return out
        except Cancelled:
            raise
        except Exception as exc:
            last = exc
            if not any(w in str(exc).lower() for w in _RETRY_WORDS):
                raise
    raise last


def _extract_stream(yt, url, fast):
    base = {"socket_timeout": 12, "format": "bestaudio[ext=m4a]/bestaudio/best", "skip_download": True}

    def run(opts):
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or not (info.get("url") or info.get("formats")):
            raise OnlineError("No video formats found")
        return info
    return _with_clients(base, run, fast)


VR_UA = "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
_fast_bad = {}                    # songs whose quick address failed: use the full engine for them


NO_NET = "No internet connection. Check your network and try again."
PIPED = ("https://pipedapi.kavin.rocks", "https://pipedapi.adminforge.de", "https://api.piped.private.coffee")


def is_network_error(exc):
    """True for 'the internet is not reachable' (not for 'the server said no')."""
    if isinstance(exc, OnlineError):
        return str(exc).startswith("No internet")
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
        return True
    low = str(exc).lower()
    return any(k in low for k in ("getaddrinfo", "name or service", "timed out", "network is unreachable",
                                  "failed to resolve", "connection reset", "temporary failure", "no route to host",
                                  "remote end closed", "connection aborted", "unable to download"))


def _json_post_keepalive(host, path, payload, headers, timeout=8):
    """POST JSON over a kept-alive HTTPS connection (one per thread and host)."""
    import gzip
    import http.client
    conns = getattr(_tls, "hosts", None)
    if conns is None:
        conns = _tls.hosts = {}
    last = None
    for attempt in range(2):                      # a kept-alive connection may have been closed by the server
        c = None if attempt else conns.get(host)
        if c is None:
            c = conns[host] = http.client.HTTPSConnection(host, timeout=timeout)
        try:
            c.timeout = timeout
            c.request("POST", path, payload, headers)
            resp = c.getresponse()
            raw = resp.read()
            if resp.status >= 400:
                raise urllib.error.HTTPError(host, resp.status, resp.reason, resp.headers, None)
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            last = exc
            try:
                c.close()
            except Exception:
                pass
            conns.pop(host, None)
    raise last


_QUICK_CLIENTS = (
    # (name, header id, payload client, user agent)
    ("ANDROID_VR", "28", {"clientName": "ANDROID_VR", "clientVersion": "1.60.19", "deviceMake": "Oculus",
                          "deviceModel": "Quest 3", "androidSdkVersion": 32, "osName": "Android", "osVersion": "12L",
                          "hl": "en", "gl": "US"}, VR_UA),
    ("IOS", "5", {"clientName": "IOS", "clientVersion": "19.45.4", "deviceMake": "Apple", "deviceModel": "iPhone16,2",
                  "osName": "iPhone", "osVersion": "18.1.0.22B83", "hl": "en", "gl": "US"},
     "com.google.ios.youtube/19.45.4 (iPhone16,2; U; CPU iOS 18_1_0 like Mac OS X;)"),
    ("ANDROID_MUSIC", "21", {"clientName": "ANDROID_MUSIC", "clientVersion": "7.27.52", "androidSdkVersion": 30,
                             "osName": "Android", "osVersion": "11", "hl": "en", "gl": "US"},
     "com.google.android.apps.youtube.music/7.27.52 (Linux; U; Android 11) gzip"),
)


def _quick_one(vid, client):
    name, cid, ctx, ua = client
    body = {"videoId": vid, "contentCheckOk": True, "racyCheckOk": True, "context": {"client": ctx}}
    data = _json_post_keepalive(
        "www.youtube.com", "/youtubei/v1/player?prettyPrint=false", json.dumps(body).encode("utf-8"),
        {"User-Agent": ua, "Content-Type": "application/json", "X-YouTube-Client-Name": cid,
         "X-YouTube-Client-Version": ctx["clientVersion"], "Accept-Encoding": "gzip"})
    if (data.get("playabilityStatus") or {}).get("status") != "OK":
        raise OnlineError(f"{name} refused")
    fmts = [f for f in (data.get("streamingData") or {}).get("adaptiveFormats", [])
            if f.get("url") and str(f.get("mimeType", "")).startswith("audio/")]
    if not fmts:
        raise OnlineError(f"{name}: no audio")
    mp4 = [f for f in fmts if "mp4" in f["mimeType"]]
    pick = max(mp4 or fmts, key=lambda f: int(f.get("bitrate") or 0))
    dur = int(float((data.get("videoDetails") or {}).get("lengthSeconds") or 0) * 1000)
    return pick["url"], dur


def _resolve_quick(vid):
    """Direct stream address, fast: the three app 'clients' are asked AT THE SAME TIME and the first good answer
    wins (~0.3 s). A song that one client refuses is usually accepted by another."""
    import queue
    q = queue.Queue()

    def work(client):
        try:
            q.put((True, _quick_one(vid, client)))
        except Exception as exc:
            q.put((False, exc))

    for c in _QUICK_CLIENTS:
        threading.Thread(target=work, args=(c,), daemon=True, name="nilkon-quick").start()
    errors = []
    for _ in _QUICK_CLIENTS:
        ok, val = q.get()
        if ok:
            return val
        errors.append(val)
    net = [e for e in errors if is_network_error(e)]
    if len(net) == len(errors):
        raise net[0]
    raise OnlineError("quick address refused")


def _resolve_piped(vid):
    """Last resort: a public relay (Piped) that returns stream addresses when the main service asks for verification."""
    last = None
    for base in PIPED:
        try:
            req = urllib.request.Request(f"{base}/streams/{vid}", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            fmts = [s for s in data.get("audioStreams", []) if s.get("url") and not s.get("videoOnly")]
            if not fmts:
                continue
            mp4 = [s for s in fmts if "mp4" in str(s.get("mimeType", "")) or s.get("format") == "M4A"]
            pick = max(mp4 or fmts, key=lambda s: int(s.get("bitrate") or 0))
            return pick["url"], int((data.get("duration") or 0) * 1000)
        except Exception as exc:
            last = exc
    raise OnlineError("relay unavailable") from last


_inflight = {}


def resolve(item):
    """-> (direct audio url, duration_ms). Cached for a while so replays and prefetched songs start at once.
    Two callers asking for the same song share one lookup."""
    key = item["key"]
    for _ in range(2):
        with _resolve_lock:
            hit = _resolve_cache.get(key)
            if hit and time.monotonic() - hit[2] < RESOLVE_TTL:
                return hit[0], hit[1]
            ev = _inflight.get(key)
            if ev is None:
                ev = _inflight[key] = threading.Event()
                mine = True
            else:
                mine = False
        if mine:
            break
        ev.wait(25)                                # somebody else is already looking this song up
    else:
        mine = True
        with _resolve_lock:
            ev = _inflight.setdefault(key, threading.Event())
    try:
        url, dur = _resolve_uncached(item)
        with _resolve_lock:
            _resolve_cache[key] = (url, dur, time.monotonic())
            for k in [k for k, v in _resolve_cache.items() if time.monotonic() - v[2] > RESOLVE_TTL][:50]:
                _resolve_cache.pop(k, None)
        return url, dur
    finally:
        with _resolve_lock:
            _inflight.pop(key, None)
        ev.set()


def _resolve_uncached(item):
    key = item["key"]
    youtube = item.get("provider", "youtube") == "youtube"
    if youtube and not _fast_bad.get(key):
        try:
            return _resolve_quick(item["id"])
        except Exception as exc:
            if is_network_error(exc):
                raise OnlineError(NO_NET) from exc
            # otherwise: the quick way was refused -> the full engine
    first = None
    try:
        yt = _ytdlp()
        info = None
        if _fast_ok[0]:
            try:
                info = _extract_stream(yt, _watch_url(item), True)
                if not (info or {}).get("url") and not (info or {}).get("formats"):
                    info = None
            except Exception as exc:
                info = None
                if is_network_error(exc):
                    raise
                _fast_ok[0] = False
        if info is None:
            info = _extract_stream(yt, _watch_url(item), False)
        url = info.get("url")
        if not url:
            fmts = [f for f in info.get("formats", []) if f.get("url") and f.get("acodec") not in (None, "none")]
            if not fmts:
                raise OnlineError("No playable audio was found for this song.")
            url = fmts[-1]["url"]
        return url, int((info.get("duration") or 0) * 1000)
    except OnlineError as exc:
        first = exc
    except Exception as exc:
        if is_network_error(exc):
            raise OnlineError(NO_NET) from exc
        first = OnlineError(friendly_error(exc))
        first.__cause__ = exc
    if youtube:                                    # the main service refused: try the public relay
        try:
            return _resolve_piped(item["id"])
        except Exception:
            pass
    raise first


def forget_all():
    with _resolve_lock:
        _resolve_cache.clear()
    _fast_ok[0] = True


def forget(key, bad=False):
    """Drop a cached stream URL (it expired). bad=True: the quick address was refused for this song, so the next
    lookup uses the full engine."""
    with _resolve_lock:
        _resolve_cache.pop(key, None)
    if bad:
        _fast_bad[key] = True
        if len(_fast_bad) > 400:
            _fast_bad.pop(next(iter(_fast_bad)), None)


def warmup():
    """Called once in the background at start: loads the music engine and opens the first connections so the first
    song does not pay for them."""
    try:
        _ytdlp()
    except Exception:
        pass
    try:
        _conn().connect()
    except Exception:
        pass
    try:
        import socket
        for h in ("www.youtube.com", "music.youtube.com"):
            try:
                socket.getaddrinfo(h, 443)
            except OSError:
                pass
    except Exception:
        pass


def fetch_audio_file(url, dest_dir, stem, cancelled, chunk=1 << 20, limit=60 << 20):
    """Fetch a direct stream URL into dest_dir with ranged requests. Returns the file path."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    mime = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("mime", ["audio/mp4"])[0]
    ext = ".m4a" if "mp4" in mime else ".webm" if "webm" in mime else ".audio"
    final = dest / (safe_name(stem, 60) + ext)
    part = final.with_suffix(ext + ".part")
    try:
        with open(part, "wb") as f:
            start, total = 0, None
            while total is None or start < total:
                if cancelled():
                    raise Cancelled()
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                           "Range": f"bytes={start}-{start + chunk - 1}"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read(limit)
                    cr = r.headers.get("Content-Range", "")
                    if r.status == 200:                       # server ignored the range: whole file
                        f.write(data)
                        break
                    total = int(cr.rsplit("/", 1)[-1]) if "/" in cr and cr.rsplit("/", 1)[-1].isdigit() else start + len(data)
                f.write(data)
                start += len(data)
                if not data or start > limit:
                    break
        if part.stat().st_size < 4096:
            raise OnlineError("The audio could not be fetched.")
        os.replace(part, final)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return str(final)


def yt_download(item, dest_dir, fmt, progress, cancelled, plain=False):
    """Download to dest_dir. Returns the final file path."""
    yt = _ytdlp()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ffmpeg = None if plain else find_ffmpeg()
    stem = safe_name(item["title"])
    base = {"noprogress": True, "socket_timeout": 15,
            "retries": 3, "fragment_retries": 3, "windowsfilenames": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(dest / (stem + " [%(id)s].%(ext)s"))}

    def hook(d):
        if cancelled():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(min(0.97, d.get("downloaded_bytes", 0) / float(total)))
    base["progress_hooks"] = [hook]
    opts = base
    pps = []
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
        if fmt == "mp3":
            pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"})
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
        opts["writethumbnail"] = True
        pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        pps.append({"key": "EmbedThumbnail"})
        opts["postprocessors"] = pps
    def run(o):
        with yt.YoutubeDL(o) as ydl:
            return ydl.extract_info(_watch_url(item), download=True)
    info = _with_clients(base, run)
    path = ""
    for rd in (info or {}).get("requested_downloads") or []:
        if rd.get("filepath") and os.path.isfile(rd["filepath"]):
            path = rd["filepath"]
    if not path:
        for pattern in AUDIO_GLOBS:
            hits = glob.glob(glob.escape(str(dest / (stem + f" [{item['id']}]"))) + pattern[1:])
            if hits:
                path = hits[0]
                break
    if not path:
        raise OnlineError("The download finished but the file could not be found.")
    if not ffmpeg and not plain:                    # no ffmpeg -> add tags/cover ourselves
        cover = None
        try:
            cover = fetch_bytes(item["thumb_url"]) if item.get("thumb_url") else None
        except Exception:
            pass
        tag_file(path, item["title"], item["artist"], cover)
    progress(1.0)
    return path


def cleanup_partial(folder, item):
    """Remove leftovers of an interrupted download of `item` from `folder`."""
    try:
        pattern = str(Path(glob.escape(str(folder))) / ("*" + glob.escape("[" + item["id"] + "]") + "*"))
        for f in glob.glob(pattern):
            if Path(f).suffix.lower() in (".part", ".ytdl", ".temp", ".tmp", ".webp", ".jpg", ".png"):
                try:
                    os.remove(f)
                except OSError:
                    pass
    except Exception:
        pass


# -- fast download ------------------------------------------------------------------------------------------
_dl_locks = {}
_dl_locks_guard = threading.Lock()


def fast_download(item, dest_dir, fmt, progress, cancelled):
    """Download in parallel pieces straight from the stream address (several times faster than the extractor's
    single connection), tag it, and move it into the library folder."""
    import fastfetch
    key = item["key"]
    with _dl_locks_guard:
        lock = _dl_locks.setdefault(key, threading.Lock())
    with lock:                                          # the same song never downloads twice at once
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        tmp = Path.home() / ".nilkon_music" / "dl_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        url, _dur = resolve(item)
        mime = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("mime", ["audio/mp4"])[0]
        ext = ".m4a" if "mp4" in mime else ".webm" if "webm" in mime else ".m4a"
        part = tmp / f"{safe_name(item['id'], 30)}-{int(time.time() * 1000)}{ext}.part"
        out = None
        try:
            def refresh():
                forget(key, bad=True)
                return resolve(item)[0]
            try:
                fastfetch.fetch_to_file(url, part, cancelled, lambda f: progress(f * 0.9), refresh=refresh)
            except fastfetch.FetchError as exc:
                if cancelled():
                    raise Cancelled()
                raise OnlineError(str(exc))
            if cancelled():
                raise Cancelled()
            work = part.with_suffix("")                  # ....m4a / ....webm
            os.replace(part, work)
            part = work
            ffmpeg = find_ffmpeg()
            if ext == ".webm" and not ffmpeg:
                raise OnlineError("webm needs the converter")
            if (fmt == "mp3" or ext == ".webm") and ffmpeg:
                import subprocess
                target = part.with_suffix(".mp3" if fmt == "mp3" else ".m4a")
                if target == part:
                    target = part.with_name(part.stem + "-c" + part.suffix)
                cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(part), "-vn"]
                cmd += ["-codec:a", "libmp3lame", "-b:a", "192k"] if fmt == "mp3" else ["-codec:a", "aac", "-b:a", "160k"]
                cmd.append(str(target))
                flags = 0x08000000 if os.name == "nt" else 0
                r = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=300)
                if r.returncode != 0 or not target.exists():
                    raise OnlineError("conversion failed")
                try:
                    part.unlink()
                except OSError:
                    pass
                part = target
            progress(0.94)
            cover = None
            try:
                cover = fetch_bytes(item["thumb_url"]) if item.get("thumb_url") else None
            except Exception:
                pass
            tag_file(str(part), item["title"], item["artist"], cover)
            if cancelled():
                raise Cancelled()
            final = dest / (safe_name(item["title"]) + f" [{item['id']}]" + part.suffix)
            out = fastfetch.move_with_retry(part, final)
            progress(1.0)
            return out
        finally:
            for f in (part,):
                try:
                    if out is None and f.exists():
                        f.unlink()
                except OSError:
                    pass


# -- registry -----------------------------------------------------------------------------------------------
def download(item, dest_dir, fmt, progress, cancelled, plain=False):
    """plain=True: just fetch the audio (used for the temporary copy that feeds the visualiser)."""
    try:
        if not plain:
            try:
                return fast_download(item, dest_dir, fmt, progress, cancelled)
            except Cancelled:
                raise
            except Exception:
                if cancelled():
                    raise Cancelled()
                progress(0.0)                          # the fast way failed: the full engine takes over
        return yt_download(item, dest_dir, fmt, progress, cancelled, plain)
    except Cancelled:
        raise
    except OnlineError:
        raise
    except Exception as exc:
        raise OnlineError(friendly_error(exc)) from exc
