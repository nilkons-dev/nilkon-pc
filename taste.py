"""Learns what the user likes and builds the "Made for you" list of the Online page (Qt-free).

Signals it learns from (all stay on this PC, in ~/.nilkon_music/taste.json):
  * words the user searches for, and the songs they then start
  * songs that are played to the end (good) or skipped within a few seconds (bad)
  * favourites (hearts), also for songs in the local library
With no history yet the list is a random mix of popular moods / languages, so the first visit already shows something.
After a few searches and plays it follows the user's artists, favourite songs ("radio" of the songs they finish) and words.
"""
import json
import math
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CURATED = [
    "Bollywood hits", "Arijit Singh", "Bangla songs", "Bengali romantic songs", "Hindi lofi", "Punjabi hits",
    "Sufi songs", "Coke Studio", "Pakistani songs", "Tamil hits", "Telugu hits", "Indie pop", "Pop hits", "Top English songs",
    "Hip hop", "Rap classics", "Rock classics", "Alternative rock", "Acoustic covers", "Chill vibes", "Lofi beats",
    "Study music", "Workout music", "EDM hits", "House music", "K-pop hits", "Arabic songs", "Latin hits", "Reggaeton",
    "R&B", "Soul", "Jazz", "Piano instrumental", "Old Hindi songs", "Ghazal", "Qawwali", "Romantic songs",
    "Sad songs", "Party songs", "Road trip songs", "Nasheed", "Country songs", "90s hits", "2000s hits",
]
COLD_LIMIT = 2.5          # below this much "taste", the list is a random mix
SHOWN_MAX = 200
PLAYED_MAX = 300
LIMITS = {"artists": 400, "terms": 200, "seeds": 150}


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def primary_artist(artist):
    """'A & B feat. C' -> 'a'"""
    a = norm(artist)
    return re.split(r"\s*(?:,|&|\bfeat\.?\b|\bft\.?\b|\bx\b|\band\b)\s*", a)[0].strip()


def _song_sig(item):
    return norm(re.sub(r"[\(\[].*?[\)\]]", "", item.get("title", ""))) + "|" + primary_artist(item.get("artist", ""))


class Taste:
    def __init__(self, folder):
        self.path = Path(folder) / "taste.json"
        self.lock = threading.RLock()
        self.artists = {}
        self.terms = {}
        self.seeds = {}                  # video id -> {"id","title","artist","w"}
        self.shown = []
        self.played = []
        self.events = 0
        self._dirty = False
        self._recorded_queries = set()
        self.load()

    # -- storage ----------------------------------------------------------------------------------
    def load(self):
        try:
            d = json.loads(self.path.read_text("utf-8"))
        except Exception:
            return
        if not isinstance(d, dict):
            return
        with self.lock:
            for name in ("artists", "terms"):
                v = d.get(name)
                if isinstance(v, dict):
                    setattr(self, name, {str(k): float(x) for k, x in v.items() if isinstance(x, (int, float))})
            v = d.get("seeds")
            if isinstance(v, dict):
                self.seeds = {k: s for k, s in v.items() if isinstance(s, dict) and s.get("id")}
            self.shown = [str(x) for x in d.get("shown", [])][-SHOWN_MAX:]
            self.played = [str(x) for x in d.get("played", [])][-PLAYED_MAX:]
            self.events = int(d.get("events", 0) or 0)

    def save(self, force=False):
        with self.lock:
            if not self._dirty and not force:
                return
            data = {"artists": self.artists, "terms": self.terms, "seeds": self.seeds, "shown": self.shown[-SHOWN_MAX:],
                    "played": self.played[-PLAYED_MAX:], "events": self.events}
            self._dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def reset(self):
        with self.lock:
            self.artists, self.terms, self.seeds, self.shown, self.played, self.events = {}, {}, {}, [], [], 0
            self._recorded_queries = set()
            self._dirty = True
        self.save()

    # -- learning ---------------------------------------------------------------------------------
    @staticmethod
    def _bump(d, key, dv, lo=-12.0, hi=40.0):
        if not key:
            return
        d[key] = max(lo, min(hi, d.get(key, 0.0) + dv))

    def _touch(self):
        self._dirty = True
        self.events += 1
        if self.events % 25 == 0:                       # old taste fades slowly
            for d in (self.artists, self.terms):
                for k in list(d):
                    d[k] *= 0.96 if d[k] > 0 else 0.9
                    if abs(d[k]) < 0.15:
                        del d[k]
            for s in self.seeds.values():
                s["w"] = s.get("w", 0) * 0.96
        for name, cap in LIMITS.items():
            d = getattr(self, name)
            if len(d) > cap:
                if name == "seeds":
                    keep = sorted(d.items(), key=lambda kv: kv[1].get("w", 0), reverse=True)[:cap]
                else:
                    keep = sorted(d.items(), key=lambda kv: abs(kv[1]), reverse=True)[:cap]
                setattr(self, name, dict(keep))

    def _seed(self, item, dv):
        vid = item.get("id")
        if not vid or item.get("provider", "youtube") != "youtube":
            return
        s = self.seeds.get(vid)
        if s is None:
            s = self.seeds[vid] = {"id": vid, "title": item.get("title", ""), "artist": item.get("artist", ""), "w": 0.0}
        s["w"] = max(-5.0, min(30.0, s.get("w", 0.0) + dv))
        if s["w"] <= 0 and dv < 0:
            self.seeds.pop(vid, None)

    def on_search(self, query, items=()):
        q = norm(query)
        if len(q) < 2 or len(q) > 60 or q.startswith("http"):
            return
        with self.lock:
            if q in self._recorded_queries:
                return
            self._recorded_queries.add(q)
            self._bump(self.terms, q, 1.0)
            for i, it in enumerate(list(items)[:3]):
                a = primary_artist(it.get("artist", ""))
                if not a:
                    continue
                if i == 0 and (a in q or q in a):                # the search was an artist name
                    self._bump(self.artists, a, 1.6)
                else:
                    self._bump(self.artists, a, 0.1)
            self._touch()

    def on_play(self, item):
        """A song was started (online item dict or {'artist':..} for a local song)."""
        with self.lock:
            self._bump(self.artists, primary_artist(item.get("artist", "")), 0.5)
            self._seed(item, 0.5)
            if item.get("id"):
                self.played.append(item["id"])
                del self.played[:-PLAYED_MAX]
            self._touch()

    def on_listen(self, item, seconds, duration_ms=0):
        """The song stopped being played after `seconds` of real listening."""
        need = 35.0
        if duration_ms and duration_ms > 0:
            need = min(35.0, max(8.0, duration_ms / 2000.0))
        with self.lock:
            a = primary_artist(item.get("artist", ""))
            if seconds >= need:
                self._bump(self.artists, a, 1.2)
                self._seed(item, 2.0)
            elif seconds < 8.0:
                self._bump(self.artists, a, -0.6)
                self._seed(item, -1.5)
            self._touch()

    def on_like(self, item, liked):
        with self.lock:
            a = primary_artist(item.get("artist", ""))
            self._bump(self.artists, a, 3.0 if liked else -2.5)
            self._seed(item, 4.0 if liked else -3.0)
            self._touch()

    def strength(self):
        with self.lock:
            return (sum(v for v in self.artists.values() if v > 0) + sum(v for v in self.terms.values() if v > 0)
                    + sum(max(0.0, s.get("w", 0)) for s in self.seeds.values()))

    # -- building the list ---------------------------------------------------------------------------
    @staticmethod
    def _pick(weighted, k, rnd):
        """k distinct keys, randomly, the more weight the more likely (no repeats)."""
        pool = [(key, w) for key, w in weighted if w > 0]
        out = []
        while pool and len(out) < k:
            total = sum(w for _, w in pool)
            r = rnd.random() * total
            acc = 0.0
            for i, (key, w) in enumerate(pool):
                acc += w
                if r <= acc:
                    out.append(key)
                    pool.pop(i)
                    break
        return out

    def build(self, n, search_fn, related_fn, rnd=None):
        """-> (items, label).  search_fn(query, limit) and related_fn(item, limit) return lists of online items."""
        rnd = rnd or random.Random()
        with self.lock:
            artists = dict(self.artists)
            terms = dict(self.terms)
            seeds = {k: dict(v) for k, v in self.seeds.items()}
            shown = set(self.shown)
            played = set(self.played)
        cold = self.strength() < COLD_LIMIT
        jobs = []
        if cold:
            for q in rnd.sample(CURATED, 5):
                jobs.append(("explore", 1.0, lambda q=q: search_fn(q, 14)))
            label = "Random picks to get started"
        else:
            for sid in self._pick([(k, s.get("w", 0)) for k, s in seeds.items()], 3, rnd):
                s = seeds[sid]
                seed_item = {"id": s["id"], "key": "online:youtube:" + s["id"], "title": s.get("title", ""),
                             "artist": s.get("artist", ""), "provider": "youtube"}
                jobs.append(("related", 1.25, lambda it=seed_item: related_fn(it, 22)))
            asked = set()
            for t in self._pick(list(terms.items()), 2, rnd):
                asked.add(t)
                jobs.append(("term", 1.0, lambda t=t: search_fn(t, 14)))
            for a in self._pick([(k, v) for k, v in artists.items() if v >= 1.0 and k not in terms], 2, rnd):
                if a not in asked:
                    asked.add(a)
                    jobs.append(("artist", 1.1, lambda a=a: search_fn(a, 14)))
            jobs.append(("explore", 0.55, lambda q=rnd.choice(CURATED): search_fn(q, 12)))
            label = "Made for you"
        results, errors = [], []

        def run(job):
            kind, w, fn = job
            try:
                return kind, w, list(fn() or [])
            except Exception as exc:
                errors.append(exc)
                return kind, w, []
        with ThreadPoolExecutor(max_workers=min(5, max(1, len(jobs)))) as pool:
            results = list(pool.map(run, jobs))
        cand = {}
        for kind, w, items in results:
            for rank, it in enumerate(items):
                vid = it.get("id")
                dur = int(it.get("duration_ms") or 0)
                if not vid or (dur and not (60_000 <= dur <= 15 * 60_000)):
                    continue
                aff = artists.get(primary_artist(it.get("artist", "")), 0.0)
                score = w * (1.0 - rank * 0.025) + 0.9 * math.tanh(aff / 6.0) - (2.5 if vid in played else 0.0) \
                    - (0.6 if vid in shown else 0.0) + rnd.random() * 0.7
                if aff <= -1.5:
                    score -= 1.5
                if vid not in cand or cand[vid][1] < score:
                    cand[vid] = (it, score)
        ranked = sorted(cand.values(), key=lambda x: x[1], reverse=True)
        fresh = [r for r in ranked if r[0]["id"] not in played]
        if len(fresh) >= min(n, 8):                        # songs already played are only shown when nothing else is left
            ranked = fresh
        out, per_artist, sigs = [], {}, set()
        for it, _ in ranked:
            sig = _song_sig(it)
            a = primary_artist(it.get("artist", ""))
            if sig in sigs or per_artist.get(a, 0) >= 3:
                continue
            sigs.add(sig)
            per_artist[a] = per_artist.get(a, 0) + 1
            out.append(it)
            if len(out) >= n:
                break
        if not out and errors:
            raise errors[0]
        with self.lock:
            self.shown.extend(i["id"] for i in out)
            del self.shown[:-SHOWN_MAX]
            self._dirty = True
        return out, label
