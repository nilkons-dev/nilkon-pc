"""Playlist sharing and importing (Qt-free).

* Share code  - "NILKON-PL1:..." : a short text a friend pastes into NILKON (Playlist + > Import > Paste share code).
* .nilkon file - the same data as a file (send it by WhatsApp / Telegram / e-mail).
* Spotify     - export the playlist to CSV (free site exportify.net), then import the CSV; every song is matched on
                the online catalogue. Also reads plain text lists ("Artist - Title" per line).
"""
import base64
import csv
import io
import json
import re
import zlib

PREFIX = "NILKON-PL1:"
FORMAT = "nilkon-playlist"


def entries_from_playlist(lib, name):
    """Playlist -> [{id?, title, artist, duration_ms}]. Online songs keep their id; local files are matched by name."""
    out = []
    for path in lib.playlists.get(name, []):
        meta = lib.meta.get(path, {}) if isinstance(lib.meta.get(path, {}), dict) else {}
        on = lib.online_meta.get(path)
        if on:
            out.append({"id": on["id"], "title": on["title"], "artist": on.get("artist", ""),
                        "duration_ms": int(on.get("duration_ms") or 0)})
        else:
            title = meta.get("title") or ""
            if title:
                out.append({"title": title, "artist": meta.get("artist", "") if meta.get("artist", "") != "Unknown artist" else "",
                            "duration_ms": int(meta.get("dur") or 0)})
    return out


def to_dict(name, entries):
    return {"format": FORMAT, "version": 1, "name": name,
            "songs": [{k: v for k, v in e.items() if v not in ("", None, 0)} for e in entries]}


def to_code(name, entries):
    raw = json.dumps(to_dict(name, entries), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")


def to_file_text(name, entries):
    return json.dumps(to_dict(name, entries), ensure_ascii=False, indent=1)


class ImportError_(ValueError):
    pass


def _clean_entries(songs):
    out, seen = [], set()
    for s in songs:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()[:300]
        vid = str(s.get("id") or "").strip()
        if vid and not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            vid = ""
        if not title and not vid:
            continue
        artist = str(s.get("artist") or "").strip()[:200]
        try:
            dur = max(0, int(s.get("duration_ms") or 0))
        except (TypeError, ValueError):
            dur = 0
        sig = vid or (title.lower(), artist.lower())
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"id": vid, "title": title or "Unknown title", "artist": artist, "duration_ms": dur})
        if len(out) >= 1000:
            break
    return out


def parse_code(text):
    text = (text or "").strip()
    i = text.find(PREFIX)
    if i < 0:
        raise ImportError_("This is not a NILKON share code.")
    code = re.split(r"\s", text[i + len(PREFIX):], 1)[0]
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ImportError_("The share code is damaged - copy it again completely.") from exc
    return _from_dict(data)


def _from_dict(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("songs"), list):
        raise ImportError_("This is not a NILKON playlist.")
    entries = _clean_entries(data["songs"])
    if not entries:
        raise ImportError_("The playlist has no songs.")
    return str(data.get("name") or "Imported playlist")[:80], entries


_TITLE_COLS = ("track name", "track", "title", "name", "song", "song name")
_ARTIST_COLS = ("artist name(s)", "artist name", "artists", "artist", "artist(s)")


def parse_file_text(text, filename=""):
    """.nilkon (JSON), Spotify / Exportify CSV, other CSV with title + artist columns, or one 'Artist - Title' per line."""
    text = (text or "").lstrip("\ufeff")
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", (filename or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    s = text.strip()
    if not s:
        raise ImportError_("The file is empty.")
    if s.startswith("{"):
        try:
            return _from_dict(json.loads(s))
        except ValueError as exc:
            if isinstance(exc, ImportError_):
                raise
            raise ImportError_("The file could not be read.") from exc
    if s.startswith(PREFIX):
        return parse_code(s)
    name = stem or "Imported playlist"
    first = s.splitlines()[0]
    if "," in first or ";" in first or "\t" in first:
        try:
            dialect = csv.Sniffer().sniff(first, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(s), dialect))
        head = [c.strip().lower() for c in rows[0]]
        ti = next((head.index(c) for c in _TITLE_COLS if c in head), -1)
        ai = next((head.index(c) for c in _ARTIST_COLS if c in head), -1)
        di = next((head.index(c) for c in ("track duration (ms)", "duration (ms)", "duration_ms") if c in head), -1)
        if ti >= 0:
            songs = []
            for r in rows[1:]:
                if len(r) <= ti or not r[ti].strip():
                    continue
                artist = r[ai].strip() if 0 <= ai < len(r) else ""
                artist = artist.replace(";", ", ")
                dur = 0
                if 0 <= di < len(r) and r[di].strip().isdigit():
                    dur = int(r[di])
                songs.append({"title": r[ti].strip(), "artist": artist, "duration_ms": dur})
            entries = _clean_entries(songs)
            if not entries:
                raise ImportError_("No songs were found in this file.")
            return name, entries
    songs = []
    for line in s.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.split(r"\s+[-–—]\s+", line, 1)
        songs.append({"artist": m[0], "title": m[1]} if len(m) == 2 else {"title": line})
    entries = _clean_entries(songs)
    if not entries:
        raise ImportError_("No songs were found in this file.")
    return name, entries


def _norm(t):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower())
    return set(re.findall(r"[\w']+", t))


def pick_match(entry, results):
    """Best search result for a wanted song (title words + artist + length), or None when nothing fits."""
    want_t, want_a = _norm(entry["title"]), _norm(entry.get("artist", ""))
    best, best_score = None, 0.0
    for r in results or []:
        rt, ra = _norm(r.get("title", "")), _norm(r.get("artist", ""))
        if not want_t:
            continue
        title_hit = len(want_t & (rt | ra)) / float(len(want_t))
        artist_hit = (len(want_a & (ra | rt)) / float(len(want_a))) if want_a else 0.5
        score = 0.65 * title_hit + 0.35 * artist_hit
        d, w = int(r.get("duration_ms") or 0), int(entry.get("duration_ms") or 0)
        if d and w:
            score += 0.15 if abs(d - w) < 6000 else (-0.25 if abs(d - w) > 45000 else 0.0)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 0.5 else None
