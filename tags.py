"""Optional metadata / cover-art reading through mutagen (falls back gracefully)."""
import base64
import os

try:
    from mutagen import File as MFile
except Exception:  # mutagen missing or broken -> app still works with file names
    MFile = None


def _first(f, key):
    try:
        v = f.get(key)
    except Exception:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip() if v else ""


def read_meta(path):
    out = {"title": "", "artist": "", "album": "", "dur": 0, "bitrate": 0}
    if MFile is None:
        return out
    try:
        f = MFile(path, easy=True)
    except Exception:
        f = None
    if f is None:
        return out
    try:
        info = f.info
        out["dur"] = int(float(getattr(info, "length", 0) or 0) * 1000)
        out["bitrate"] = int(float(getattr(info, "bitrate", 0) or 0) / 1000)
    except Exception:
        pass
    out["title"] = _first(f, "title")
    out["artist"] = _first(f, "artist")
    out["album"] = _first(f, "album")
    return out


FOLDER_NAMES = ("cover", "folder", "front", "album", "albumart", "art")
FOLDER_EXTS = (".jpg", ".jpeg", ".png")


def folder_cover(path):
    """cover.jpg / folder.png ... sitting next to the audio file, as bytes (or None)."""
    try:
        folder = os.path.dirname(path)
        found = {}
        for name in os.listdir(folder):
            stem, ext = os.path.splitext(name)
            if ext.lower() in FOLDER_EXTS and stem.lower() in FOLDER_NAMES:
                found[stem.lower()] = name
        for stem in FOLDER_NAMES:
            if stem in found:
                with open(os.path.join(folder, found[stem]), "rb") as fh:
                    return fh.read(8 * 1024 * 1024)
    except OSError:
        pass
    return None


def read_cover(path):
    """Cover art for a song as bytes: embedded picture first, then a folder image."""
    return embedded_cover(path) or folder_cover(path)


def embedded_cover(path):
    """Embedded cover art as bytes, or None."""
    if MFile is None:
        return None
    try:
        f = MFile(path)
    except Exception:
        return None
    if f is None:
        return None
    try:
        pics = getattr(f, "pictures", None)  # FLAC
        if pics:
            return bytes(pics[0].data)
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):  # ID3 (mp3)
            apics = tags.getall("APIC")
            if apics:
                return bytes(apics[0].data)
        try:
            if "covr" in tags:  # MP4 / m4a
                covr = tags["covr"]
                if covr:
                    return bytes(covr[0])
        except Exception:
            pass
        mbp = tags.get("metadata_block_picture") if hasattr(tags, "get") else None  # Ogg
        if mbp:
            from mutagen.flac import Picture
            return bytes(Picture(base64.b64decode(mbp[0])).data)
    except Exception:
        return None
    return None
