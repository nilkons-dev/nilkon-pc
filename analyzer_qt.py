"""Real audio analysis for the visualisers.

Strategy (first that works wins, otherwise the engine keeps its simulated visualiser):
  1. `miniaudio` (mp3 / wav / flac / ogg) decoded in a background thread - fast and reliable.
  2. Qt Multimedia's QAudioDecoder (other codecs, if the platform backend supports them).
"""
import os
import subprocess
import sys
import threading
from collections import OrderedDict

from PySide6.QtCore import QObject, QUrl, Signal

import audio_analysis as aa
from thread_bridge import Mailbox

np = aa.np

try:
    import miniaudio
except Exception:
    miniaudio = None

try:
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
    HAVE_DECODER = True
except Exception:
    HAVE_DECODER = False

MAX_SECONDS = 45 * 60
TARGET_RATE = 32000


def decode_with_miniaudio(path):
    """Whole file -> (mono float32 samples, sample rate)."""
    if miniaudio is None or np is None:
        raise RuntimeError("miniaudio not available")
    try:
        info = miniaudio.get_file_info(path)
        if info.duration > MAX_SECONDS:
            raise ValueError("file too long for analysis")
    except ValueError:
        raise
    except Exception:
        pass  # unknown container: let decode_file decide
    snd = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.SIGNED16,
                                nchannels=1, sample_rate=TARGET_RATE)
    arr = np.frombuffer(snd.samples, dtype=np.int16).astype(np.float32) / 32768.0
    return arr, int(snd.sample_rate)


def decode_with_ffmpeg(path):
    """Any format ffmpeg knows (m4a/AAC, webm/opus ...) -> (mono float32 samples, sample rate)."""
    if np is None:
        raise RuntimeError("numpy not available")
    try:
        from online import find_ffmpeg
        exe = find_ffmpeg()
    except Exception:
        exe = None
    if not exe:
        raise RuntimeError("ffmpeg not available")
    cmd = [exe, "-v", "quiet", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(TARGET_RATE),
           "-t", str(MAX_SECONDS), "-f", "s16le", "-"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags, timeout=240)
    if r.returncode != 0 or len(r.stdout) < 4096:
        raise RuntimeError("ffmpeg could not decode the file")
    arr = np.frombuffer(r.stdout[: len(r.stdout) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    return arr, TARGET_RATE


_FFMPEG_FIRST = (".m4a", ".mp4", ".aac", ".webm", ".opus", ".audio", ".wma", ".alac")


def decode_any(path):
    """miniaudio for the formats it knows (fast), ffmpeg for the rest; each is the other's fallback."""
    order = (decode_with_ffmpeg, decode_with_miniaudio) if os.path.splitext(path)[1].lower() in _FFMPEG_FIRST \
        else (decode_with_miniaudio, decode_with_ffmpeg)
    last = None
    for fn in order:
        try:
            return fn(path)
        except ValueError:
            raise
        except Exception as exc:
            last = exc
    raise RuntimeError(str(last))


def analyse_samples(samples, sr, should_cancel=lambda: False):
    an = aa.SpectrumAnalyzer(sr)
    step = int(sr * 5)
    for i in range(0, len(samples), step):
        if should_cancel():
            return None
        an.feed(samples[i:i + step])
    an.finish()
    return an


def _buffer_bytes(buf):
    n = buf.byteCount()
    for getter in ("constData", "data"):
        fn = getattr(buf, getter, None)
        if fn is None:
            continue
        try:
            ptr = fn()
        except Exception:
            continue
        if isinstance(ptr, (bytes, bytearray, memoryview)):
            return bytes(ptr)[:n]
        try:
            return bytes(memoryview(ptr))[:n]
        except Exception:
            pass
        try:
            ptr.setSize(n)
            return bytes(memoryview(ptr))
        except Exception:
            pass
    raise RuntimeError("cannot read audio buffer")


def _to_mono(buf):
    fmt = buf.format()
    ch = max(1, fmt.channelCount())
    sf = fmt.sampleFormat()
    F = QAudioFormat.SampleFormat
    raw = _buffer_bytes(buf)
    if sf == F.Int16:
        arr, scale, off = np.frombuffer(raw, dtype=np.int16), 32768.0, 0.0
    elif sf == F.Int32:
        arr, scale, off = np.frombuffer(raw, dtype=np.int32), 2147483648.0, 0.0
    elif sf == F.Float:
        arr, scale, off = np.frombuffer(raw, dtype=np.float32), 1.0, 0.0
    elif sf == F.UInt8:
        arr, scale, off = np.frombuffer(raw, dtype=np.uint8), 128.0, 128.0
    else:
        raise RuntimeError("unsupported sample format")
    usable = (arr.size // ch) * ch
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    x = (arr[:usable].astype(np.float32) - off) / scale
    return x.reshape(-1, ch).mean(axis=1)


def _has_ffmpeg():
    try:
        from online import find_ffmpeg
        return bool(find_ffmpeg())
    except Exception:
        return False


class TrackAnalyzer(QObject):
    """Emits `ready(path, SpectrumAnalyzer)` when the full analysis is done and
    `started(path, SpectrumAnalyzer)` as soon as a progressive analysis can be read."""
    started = Signal(str, object)
    ready = Signal(str, object)
    failed = Signal(str)
    _thread_done = Signal(int, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dec = None
        self._an = None
        self._proc = None
        self.expected_seconds = 0.0
        self._path = ""
        self._token = 0
        self._cache = OrderedDict()
        self._thread_done.connect(self._on_thread_done)
        self._mb = Mailbox(self)

    @property
    def available(self):
        return aa.AVAILABLE and (miniaudio is not None or HAVE_DECODER or _has_ffmpeg())

    def cancel(self):
        self._token += 1
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        dec, self._dec = self._dec, None
        self._an = None
        if dec is not None:
            try:
                dec.stop()
            except Exception:
                pass
            dec.deleteLater()

    def start(self, path):
        self.cancel()
        self._path = path
        if not aa.AVAILABLE:
            self.failed.emit(path)
            return False
        cached = self._cache.get(path)
        if cached is not None:
            self._cache.move_to_end(path)
            self.ready.emit(path, cached)
            return True
        if miniaudio is not None or _has_ffmpeg():
            token = self._token
            threading.Thread(target=self._local_work, args=(token, path), daemon=True).start()
            return True
        return self._start_qt(path)

    # -- live analysis of a stream: starts within a second, while the song is already playing ------
    def start_stream(self, key, url):
        """Let ffmpeg read the stream address itself and analyse the sound as it arrives (faster than playback).
        Emits started (first frames ready), then ready; failed when ffmpeg cannot open the stream."""
        self.cancel()
        self._path = key
        if not aa.AVAILABLE:
            self.failed.emit(key)
            return False
        exe = None
        try:
            from online import find_ffmpeg, USER_AGENT
            exe = find_ffmpeg()
        except Exception:
            pass
        if not exe:
            self.failed.emit(key)
            return False
        token = self._token
        threading.Thread(target=self._stream_work, args=(token, key, url, exe, USER_AGENT), daemon=True).start()
        return True

    def _stream_work(self, token, key, url, exe, ua):
        an = None
        proc = None
        total = 0
        total_seconds = 0.0
        try:
            cmd = [exe, "-v", "quiet", "-nostdin", "-user_agent", ua, "-reconnect", "1", "-reconnect_streamed", "1",
                   "-reconnect_delay_max", "3", "-i", url, "-vn", "-ac", "1", "-ar", str(TARGET_RATE),
                   "-f", "s16le", "-"]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            if token != self._token:
                return
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
            if token != self._token:                     # cancelled while starting: do not leave it running
                proc.kill()
                return
            self._proc = proc
            chunk = TARGET_RATE * 2                         # one second of 16-bit mono
            started = False
            leftover = b""
            while token == self._token:
                data = proc.stdout.read(chunk)
                if not data:
                    break
                data = leftover + data
                n = len(data) // 2 * 2
                leftover = data[n:]
                if n == 0:
                    continue
                if an is None:
                    an = aa.SpectrumAnalyzer(TARGET_RATE)
                arr = np.frombuffer(data[:n], dtype=np.int16).astype(np.float32) / 32768.0
                an.feed(arr)
                total += arr.size
                if not started and total >= TARGET_RATE // 2:
                    started = True
                    self._mb.post(self._stream_started, token, key, an)
                if total > MAX_SECONDS * TARGET_RATE:
                    break
            total_seconds = total / float(TARGET_RATE)
            if token == self._token and an is not None and total >= TARGET_RATE:
                an.finish()
            else:
                an = None
        except Exception:
            an = None
        finally:
            try:
                if proc is not None:
                    proc.kill()
                    proc.stdout.close()
                    proc.wait(timeout=2)
            except Exception:
                pass
            if self._proc is proc:
                self._proc = None
        self._mb.post(self._stream_done, token, key, an, total_seconds)

    def _stream_started(self, token, key, an):
        if token == self._token:
            self.started.emit(key, an)

    def _stream_done(self, token, key, an, seconds=0.0):
        if token != self._token:
            return
        if an is None or not an.done or an.bands.shape[0] == 0:
            self.failed.emit(key)
            return
        expected = self.expected_seconds
        if expected and seconds < expected * 0.9 - 3:        # the stream stopped early: do not trust a partial analysis
            self.failed.emit(key)
            return
        self._remember(key, an)
        self.ready.emit(key, an)

    # -- local files: progressive analysis, the waves start within a fraction of a second --------------
    _MINI_EXT = (".mp3", ".wav", ".flac", ".ogg")

    def _mini_chunks(self, token, path):
        for buf in miniaudio.stream_file(path, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                         sample_rate=TARGET_RATE, frames_to_read=TARGET_RATE // 2):
            if token != self._token:
                return
            yield np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0

    def _ffmpeg_chunks(self, token, path):
        from online import find_ffmpeg
        exe = find_ffmpeg()
        if not exe:
            raise RuntimeError("ffmpeg not available")
        cmd = [exe, "-v", "quiet", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(TARGET_RATE),
               "-t", str(MAX_SECONDS), "-f", "s16le", "-"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
        self._proc = proc
        try:
            left = b""
            while token == self._token:
                data = proc.stdout.read(TARGET_RATE)
                if not data:
                    break
                data = left + data
                n = len(data) // 2 * 2
                left = data[n:]
                if n:
                    yield np.frombuffer(data[:n], dtype=np.int16).astype(np.float32) / 32768.0
        finally:
            try:
                proc.kill()
                proc.stdout.close()
                proc.wait(timeout=2)
            except Exception:
                pass
            if self._proc is proc:
                self._proc = None

    def _run_progressive(self, token, path, chunks):
        an = None
        total = 0
        started = False
        for arr in chunks:
            if token != self._token:
                return None
            if arr.size == 0:
                continue
            if an is None:
                an = aa.SpectrumAnalyzer(TARGET_RATE)
            an.feed(arr)
            total += arr.size
            if not started and total >= TARGET_RATE // 2:
                started = True
                self._mb.post(self._stream_started, token, path, an)
            if total > MAX_SECONDS * TARGET_RATE:
                break
        if token != self._token or an is None or total < TARGET_RATE // 2:
            return None
        an.finish()
        return an

    def _local_work(self, token, path):
        an = None
        ext = os.path.splitext(path)[1].lower()
        sources = []
        if miniaudio is not None and ext in self._MINI_EXT:
            sources.append(lambda: self._mini_chunks(token, path))
        sources.append(lambda: self._ffmpeg_chunks(token, path))
        for make in sources:
            try:
                an = self._run_progressive(token, path, make())
            except Exception:
                an = None
            if an is not None or token != self._token:
                break
        if an is None and token == self._token:
            try:                                   # last resort: whole-file decode
                samples, sr = decode_any(path)
                an = analyse_samples(samples, sr, lambda: token != self._token)
            except Exception:
                an = None
        self._mb.post(self._on_thread_done, token, path, an)

    # -- miniaudio worker thread -----------------------------------------------------
    def _work(self, token, path):
        try:
            samples, sr = decode_any(path)
            an = analyse_samples(samples, sr, lambda: token != self._token)
        except Exception:
            an = None
        self._mb.post(self._on_thread_done, token, path, an)

    def _on_thread_done(self, token, path, an):
        if token != self._token:
            return
        if an is None or an.bands.shape[0] == 0:
            if not self._start_qt(path):
                self.failed.emit(path)
            return
        self._remember(path, an)
        self.ready.emit(path, an)

    def _remember(self, path, an):
        self._cache[path] = an
        while len(self._cache) > 3:
            self._cache.popitem(last=False)

    # -- Qt Multimedia fallback -------------------------------------------------------
    def _start_qt(self, path):
        if not HAVE_DECODER:
            return False
        try:
            dec = QAudioDecoder(self)
            dec.setSource(QUrl.fromLocalFile(path))
            dec.bufferReady.connect(lambda d=dec: self._on_buffer(d))
            dec.finished.connect(lambda d=dec: self._on_finished(d))
            dec.errorOccurred.connect(lambda *a, d=dec: self._on_error(d))
            self._dec = dec
            self._an = None
            dec.start()
            return True
        except Exception:
            self._dec = None
            return False

    def _on_buffer(self, dec):
        if dec is not self._dec:
            return
        try:
            while dec.bufferAvailable():
                buf = dec.read()
                if not buf.isValid():
                    break
                mono = _to_mono(buf)
                if self._an is None:
                    self._an = aa.SpectrumAnalyzer(buf.format().sampleRate())
                    self.started.emit(self._path, self._an)
                self._an.feed(mono)
        except Exception:
            self._on_error(dec)

    def _on_finished(self, dec):
        if dec is not self._dec:
            return
        an, path = self._an, self._path
        self._dec = None
        dec.deleteLater()
        if an is None:
            self.failed.emit(path)
            return
        try:
            an.finish()
            self._remember(path, an)
            self.ready.emit(path, an)
        except Exception:
            self.failed.emit(path)

    def _on_error(self, dec):
        if dec is not self._dec:
            return
        self._dec = None
        self._an = None
        try:
            dec.stop()
        except Exception:
            pass
        dec.deleteLater()
        self.failed.emit(self._path)
