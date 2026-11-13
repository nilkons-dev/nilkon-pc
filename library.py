"""Qt-free library model: tracks, playlists, likes, history, per-song EQ and settings.

Everything the player persists lives here so it can be unit-tested without a GUI.
"""
import json
import os
import random
import shutil
from pathlib import Path

APP_DIR_NAME = ".nilkon_music"
OLD_DIR_NAME = ".morrigan_music"
ALL = "All Tracks"
LIKED = "Liked Songs"
RECENT = "Recently Played"
RESERVED = (ALL, LIKED, RECENT)
EQ_BANDS = 10
HISTORY_MAX = 60

DEFAULT_SETTINGS = {
    "mode": "dark",            # dark | light
    "accent": "Cat Orange",    # key of theme.ACCENTS
    "adaptive": False,         # tint the UI from album art
    "background": "aurora",    # aurora | midnight | deepspace | bluehaze | custom
    "custom_bg": "",
    "bg_dim": 55,              # 0..90 percent darkening over an image background
    "bg_blur": 0,              # 0..100
    "wave_style": "waves",     # waves | bars | mirror
    "reduced_fx": False,
    "sync_offset": 0,          # ms, shifts the visualiser against the audio
    "volume": 75,
    "download_dir": "",             # empty -> ~/Music/NILKON
    "download_format": "mp3",       # mp3 | m4a (best quality, no re-encode)
    "discord_enabled": True,
    "discord_app_id": "",           # Application ID from discord.com/developers
    "resume_last": True,            # reopen the last song (paused) at its position
    "auto_radio": True,             # keep playing similar songs after an online song
    "volume_step": 5,               # keyboard volume step
    "seek_step": 10,                # seconds, Alt+Left / Alt+Right
    "start_page": "home",           # home | online
    "title_song": True,             # show the song name in the window title
    "toasts": True,                 # small pop-up messages
    "wave_gain": 100,               # % wave sensitivity
    "wave_smooth": 50,              # 0 snappy .. 100 smooth
    "cookie_browser": "",           # "", chrome, edge, firefox, brave - lets the music engine reuse your sign-in
    "normalize": False,             # even out loudness between songs (needs a restart)
}

ONLINE_PREFIX = "online:"


def is_online(path):
    """Virtual path of a streamed (not yet downloaded) song, e.g. 'online:youtube:abc123'."""
    return isinstance(path, str) and path.startswith(ONLINE_PREFIX)


def _clean_online(key, raw):
    if not is_online(key) or not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
        return None
    out = {"key": key, "provider": "youtube", "id": str(raw.get("id") or key.rsplit(":", 1)[-1])}
    out["title"] = raw["title"][:300]
    for f in ("artist", "thumb_url", "page_url", "cover_url"):
        v = raw.get(f, "")
        out[f] = v[:600] if isinstance(v, str) else ""
    try:
        out["duration_ms"] = max(0, int(raw.get("duration_ms", 0)))
    except (TypeError, ValueError):
        out["duration_ms"] = 0
    return out


def _online_to_meta(it):
    return {"title": it["title"], "artist": it.get("artist") or "Unknown artist", "album": "Online",
            "dur": int(it.get("duration_ms") or 0), "bitrate": 0}


def effective_preamp(eq):
    """Preamp actually sent to the player: with 'smart headroom' the boosted bands lower the level a little so
    loud songs do not clip (distort) when you push the equalizer."""
    pre = float(eq.get("preamp", 0))
    if eq.get("safe", True) and eq.get("enabled", True):
        pre -= max(0.0, float(max(eq.get("values") or [0]))) * 0.55
    return max(-20.0, min(20.0, pre))


def flat_eq():
    return {"values": [0] * EQ_BANDS, "preset": "Flat", "preamp": 0, "enabled": True, "safe": True}


def _clean_eq(raw, default=None):
    """Validate an equalizer dict loaded from disk."""
    base = default if default is not None else flat_eq()
    if not isinstance(raw, dict):
        return dict(base, values=list(base["values"]))
    vals = raw.get("values")
    if not isinstance(vals, list):
        vals = list(base["values"])
    out = []
    for v in (list(vals) + [0] * EQ_BANDS)[:EQ_BANDS]:
        try:
            out.append(max(-20, min(20, int(v))))
        except (TypeError, ValueError):
            out.append(0)
    try:
        pre = max(-20, min(20, int(raw.get("preamp", 0))))
    except (TypeError, ValueError):
        pre = 0
    return {"values": out, "preset": str(raw.get("preset", "Custom")), "preamp": pre,
            "enabled": bool(raw.get("enabled", True)), "safe": bool(raw.get("safe", True))}


class Library:
    def __init__(self, base_dir=None):
        self.dir = Path(base_dir) if base_dir else Path.home() / APP_DIR_NAME
        self.file = self.dir / "library.json"
        self.tracks = []
        self.playlists = {}          # name -> [paths]   (never contains the reserved names)
        self.liked = []
        self.meta = {}
        self.history = []            # most recent first
        self.play_counts = {}
        self.track_eq = {}
        self.downloads = {}          # online key -> local file (downloaded songs)
        self.online_seen = {}        # online key -> item, songs shown in this session (search results, radio queue)
        self.online_meta = {}        # online key -> song info, for online songs saved in playlists / favourites / history
        self.eq = flat_eq()
        self.eq_presets = {}         # name -> {'values': [...], 'preamp': n}  (the user's own equalizer presets)
        self.settings = dict(DEFAULT_SETTINGS)
        self.last_path = ""
        self.last_pos = 0

    # -- persistence -----------------------------------------------------------------
    def load(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self._migrate_old()
        data = {}
        self._protect = False
        for candidate in (self.file, self.file.with_suffix(".bak")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    break
            except (OSError, ValueError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        if not data and self.file.exists() and self.file.stat().st_size > 20:
            self._protect = True              # the file exists but could not be read: never overwrite it blindly
        self._apply(data)
        raw = data.get("tracks", []) if isinstance(data.get("tracks", []), list) else []
        if len(self.tracks) < len(set(p for p in raw if isinstance(p, str))):
            try:                              # some files are missing (drive unplugged?): keep the full list safe
                shutil.copyfile(self.file, self.dir / "library.before-cleanup.json")
            except OSError:
                pass
        return self

    def _migrate_old(self):
        old = Path.home() / OLD_DIR_NAME / "library.json"
        if self.dir == Path.home() / APP_DIR_NAME and not self.file.exists() and old.is_file():
            try:
                shutil.copyfile(old, self.file)
            except OSError:
                pass

    def _apply(self, data):
        def plist(key):
            v = data.get(key, [])
            return [p for p in v if isinstance(p, str)] if isinstance(v, list) else []

        self.tracks = []
        seen = set()
        for p in plist("tracks"):
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                self.tracks.append(p)
        self.online_meta = {}
        om = data.get("online", {})
        if isinstance(om, dict):
            for k, v in om.items():
                it = _clean_online(k, v)
                if it:
                    self.online_meta[k] = it
        tset = set(self.tracks) | set(self.online_meta)
        self.liked = [p for p in plist("liked") if p in tset]
        self.liked = list(dict.fromkeys(self.liked))
        pls = data.get("playlists", {})
        self.playlists = {}
        if isinstance(pls, dict):
            for name, items in pls.items():
                if name in RESERVED or not isinstance(name, str) or not isinstance(items, list):
                    continue
                self.playlists[name] = list(dict.fromkeys(p for p in items if p in tset))
        meta = data.get("meta", {})
        self.meta = {k: v for k, v in meta.items() if k in tset and isinstance(v, dict)} if isinstance(meta, dict) else {}
        for k, it in self.online_meta.items():
            self.meta[k] = _online_to_meta(it)
        self.history = [p for p in plist("history") if p in tset][:HISTORY_MAX]
        pc = data.get("play_counts", {})
        self.play_counts = {k: int(v) for k, v in pc.items() if k in tset and isinstance(v, (int, float))} if isinstance(pc, dict) else {}
        te = data.get("track_eq", {})
        self.track_eq = {k: _clean_eq(v) for k, v in te.items() if k in tset} if isinstance(te, dict) else {}
        dl = data.get("downloads", {})
        lset = set(self.tracks)
        self.downloads = {k: v for k, v in dl.items() if isinstance(k, str) and v in lset} if isinstance(dl, dict) else {}
        ep = data.get("eq_presets", {})
        self.eq_presets = {}
        if isinstance(ep, dict):
            for name, v in list(ep.items())[:60]:
                if isinstance(name, str) and name.strip() and isinstance(v, dict):
                    c = _clean_eq(v)
                    self.eq_presets[name.strip()[:40]] = {"values": c["values"], "preamp": c["preamp"]}
        # global EQ: new format, else the legacy flat keys
        if isinstance(data.get("eq"), dict):
            self.eq = _clean_eq(data["eq"])
        else:
            self.eq = _clean_eq({"values": data.get("eq_values", []), "preset": data.get("eq_preset", "Flat"),
                                 "preamp": data.get("eq_preamp", 0), "enabled": data.get("eq_enabled", True)})
        st = dict(DEFAULT_SETTINGS)
        raw = data.get("settings", {})
        if isinstance(raw, dict):
            for k, default in DEFAULT_SETTINGS.items():
                if k in raw and isinstance(raw[k], type(default)):
                    st[k] = raw[k]
        # legacy keys
        if "volume" in data and isinstance(data["volume"], (int, float)) and "volume" not in (raw if isinstance(raw, dict) else {}):
            st["volume"] = int(data["volume"])
        if data.get("reduced_fx") is True and "reduced_fx" not in (raw if isinstance(raw, dict) else {}):
            st["reduced_fx"] = True
        st["volume"] = max(0, min(100, int(st["volume"])))
        st["bg_dim"] = max(0, min(90, int(st["bg_dim"])))
        st["bg_blur"] = max(0, min(100, int(st["bg_blur"])))
        st["sync_offset"] = max(-400, min(400, int(st["sync_offset"])))
        st["volume_step"] = max(1, min(20, int(st["volume_step"])))
        st["seek_step"] = max(3, min(60, int(st["seek_step"])))
        st["wave_gain"] = max(50, min(170, int(st["wave_gain"])))
        st["wave_smooth"] = max(0, min(100, int(st["wave_smooth"])))
        if st["start_page"] not in ("home", "online"):
            st["start_page"] = "home"
        if st["cookie_browser"] not in ("", "chrome", "edge", "firefox", "brave", "opera", "vivaldi"):
            st["cookie_browser"] = ""
        if st["download_format"] not in ("mp3", "m4a"):
            st["download_format"] = "mp3"
        st["discord_app_id"] = "".join(ch for ch in st["discord_app_id"] if ch.isdigit())[:24]
        if st["mode"] not in ("dark", "light"):
            st["mode"] = "dark"
        if st["wave_style"] not in ("waves", "bars", "mirror"):
            st["wave_style"] = "waves"
        self.settings = st
        lp = data.get("last_path", "")
        self.last_path = lp if isinstance(lp, str) and lp in lset else ""
        try:
            self.last_pos = max(0, int(data.get("last_pos", 0)))
        except (TypeError, ValueError):
            self.last_pos = 0

    def _referenced_online(self):
        used = set(self.liked) | set(self.history) | set(self.downloads)
        for items in self.playlists.values():
            used.update(items)
        return {k: v for k, v in self.online_meta.items() if k in used}

    def save(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 2, "tracks": self.tracks, "liked": self.liked, "playlists": self.playlists,
                "meta": {k: v for k, v in self.meta.items() if not is_online(k)}, "history": self.history, "play_counts": self.play_counts,
                "track_eq": self.track_eq, "eq_presets": self.eq_presets, "downloads": self.downloads, "online": self._referenced_online(), "eq": self.eq, "settings": self.settings,
                "last_path": self.last_path, "last_pos": int(self.last_pos),
            }
            if getattr(self, "_protect", False):
                try:
                    shutil.copyfile(self.file, self.dir / "library.unreadable.json")
                except OSError:
                    pass
                self._protect = False
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
            if self.file.exists():
                try:
                    shutil.copyfile(self.file, self.file.with_suffix(".bak"))
                except OSError:
                    pass
            os.replace(tmp, self.file)
            return True
        except OSError:
            return False

    def download_dir(self):
        d = self.settings.get("download_dir") or ""
        return Path(d) if d else Path.home() / "Music" / "NILKON"

    # -- track information ------------------------------------------------------------
    def _info(self, path):
        m = self.meta.get(path)
        if m:
            return m
        if is_online(path):
            it = self.online_meta.get(path) or self.online_seen.get(path)
            if it:
                return _online_to_meta(it)
        return {}

    def title(self, path):
        m = self._info(path)
        return m.get("custom_title") or m.get("title") or Path(path).stem

    def artist(self, path):
        m = self._info(path)
        return m.get("artist") or Path(path).parent.name or "Unknown artist"

    def album(self, path):
        m = self._info(path)
        return m.get("album") or Path(path).parent.name

    def duration(self, path):
        return int(self._info(path).get("dur", 0) or 0)

    def rename(self, path, new_title):
        if path not in self.tracks:
            return False
        new_title = (new_title or "").strip()
        m = self.meta.setdefault(path, {})
        if new_title:
            m["custom_title"] = new_title
        else:
            m.pop("custom_title", None)
        return True

    # -- tracks ----------------------------------------------------------------------
    def add_tracks(self, paths):
        have = set(self.tracks)
        added = []
        for p in paths:
            try:
                p = str(Path(p).resolve())
            except OSError:
                continue
            if p not in have and os.path.isfile(p):
                have.add(p)
                self.tracks.append(p)
                added.append(p)
        return added

    def remove_track(self, path):
        self.tracks = [p for p in self.tracks if p != path]
        self.liked = [p for p in self.liked if p != path]
        self.history = [p for p in self.history if p != path]
        for name in self.playlists:
            self.playlists[name] = [p for p in self.playlists[name] if p != path]
        for d in (self.meta, self.play_counts, self.track_eq):
            d.pop(path, None)
        self.downloads = {k: v for k, v in self.downloads.items() if v != path}
        if self.last_path == path:
            self.last_path, self.last_pos = "", 0

    def see_online(self, item):
        """Remember an online song for display only (not saved)."""
        if isinstance(item, dict) and is_online(item.get("key")):
            self.online_seen[item["key"]] = item
            if len(self.online_seen) > 800:
                for k in list(self.online_seen)[:200]:
                    if k not in self.online_meta:
                        self.online_seen.pop(k, None)

    def register_online(self, item):
        """Remember an online song so it can live in playlists / favourites / history."""
        it = _clean_online(item.get("key"), item) if isinstance(item, dict) else None
        if it is None:
            return False
        self.online_meta[it["key"]] = it
        self.meta[it["key"]] = _online_to_meta(it)
        return True

    def knows(self, path):
        return path in self.online_meta or path in self._track_set()

    def _track_set(self):
        return set(self.tracks)

    # -- likes -----------------------------------------------------------------------
    def is_liked(self, path):
        return path in self.liked

    def toggle_like(self, path):
        if path not in self.online_meta and path not in self.tracks:
            return False
        if path in self.liked:
            self.liked.remove(path)
            return False
        self.liked.append(path)
        return True

    # -- playlists -------------------------------------------------------------------
    def playlist_names(self):
        return list(self.playlists.keys())

    def create_playlist(self, name):
        name = (name or "").strip()
        if not name:
            return False, "Please type a playlist name."
        if name in RESERVED or name in self.playlists:
            return False, "A playlist with this name already exists."
        if len(name) > 60:
            return False, "Playlist names can be at most 60 characters."
        self.playlists[name] = []
        return True, ""

    def rename_playlist(self, old, new):
        new = (new or "").strip()
        if old not in self.playlists:
            return False, "Playlist not found."
        if not new:
            return False, "Please type a playlist name."
        if new != old and (new in RESERVED or new in self.playlists):
            return False, "A playlist with this name already exists."
        self.playlists = {(new if k == old else k): v for k, v in self.playlists.items()}
        return True, ""

    def delete_playlist(self, name):
        return self.playlists.pop(name, None) is not None

    def add_to_playlist(self, name, path):
        if name not in self.playlists or (path not in self.tracks and path not in self.online_meta):
            return False
        if path in self.playlists[name]:
            return False
        self.playlists[name].append(path)
        return True

    def remove_from_playlist(self, name, path):
        if name in self.playlists and path in self.playlists[name]:
            self.playlists[name].remove(path)
            return True
        return False

    def collection(self, name):
        if name == ALL:
            return list(self.tracks)
        if name == LIKED:
            return list(self.liked)
        if name == RECENT:
            return list(self.history)
        return list(self.playlists.get(name, []))

    def reorder(self, name, visible_order):
        """Apply a drag-and-drop order of the *visible* items of a collection.

        Hidden items (e.g. filtered out by search) keep their slots.
        """
        if name == ALL:
            full = self.tracks
        elif name == LIKED:
            full = self.liked
        elif name in self.playlists:
            full = self.playlists[name]
        else:
            return False
        vis = [p for p in visible_order if p in full]
        vset = set(vis)
        if len(vset) != len(vis):
            return False
        it = iter(vis)
        new = [next(it) if p in vset else p for p in full]
        full[:] = new
        return True

    # -- history & suggestions -------------------------------------------------------
    def record_play(self, path):
        """Called when a song starts: updates 'recently played' and the resume point."""
        if path not in self.tracks and path not in self.online_meta:
            return
        self.history = [p for p in self.history if p != path]
        self.history.insert(0, path)
        del self.history[HISTORY_MAX:]
        if not is_online(path):
            self.last_path = path

    def record_listen(self, path):
        """Called once a song has really been listened to (not skipped)."""
        if path in self.tracks or path in self.online_meta:
            self.play_counts[path] = self.play_counts.get(path, 0) + 1

    def top_played(self, n):
        ranked = sorted((p for p in self.tracks if self.play_counts.get(p, 0) > 0),
                        key=lambda p: (-self.play_counts[p], self.tracks.index(p)))
        return ranked[:n]

    def suggestions(self, n, rnd=None, exclude=()):
        """Random picks weighted towards songs the user listens to most."""
        rnd = rnd or random
        ex = set(exclude)
        pool = [p for p in self.tracks if p not in ex]
        if not pool:
            return []
        keyed = []
        for p in pool:
            c = self.play_counts.get(p, 0)
            w = (c + 0.5) ** 1.6 if c > 0 else 0.35
            keyed.append((rnd.random() ** (1.0 / w), p))
        keyed.sort(reverse=True)
        return [p for _, p in keyed[:n]]

    def has_history(self):
        return any(v > 0 for v in self.play_counts.values())

    # -- equalizer -------------------------------------------------------------------
    def eq_for(self, path):
        return self.track_eq.get(path) or self.eq

    def set_track_eq(self, path, eq):
        if path not in self.tracks and path not in self.online_meta:
            return
        if eq is None:
            self.track_eq.pop(path, None)
        else:
            self.track_eq[path] = _clean_eq(eq)
