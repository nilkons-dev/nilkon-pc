"""Qt-free audio analysis: turns decoded PCM into a spectrum timeline.

The player feeds mono float samples (-1..1) into SpectrumAnalyzer.  The result is a
list of N_BANDS-wide frames (one every HOP samples) that the visualisers read at the
current playback position, plus a small loudness envelope used by the seek bar.
"""
import threading
import time

try:
    import numpy as np
except Exception:  # analysis is optional; the player falls back to a simulated visualiser
    np = None

AVAILABLE = np is not None

N_BANDS = 32
F_MIN = 40.0
F_MAX = 16000.0
N_FFT = 2048
HOP = 1024
DB_FLOOR = -75.0
DB_SPAN = 70.0
ENV_BINS = 480


def band_edges(sr, n_fft=N_FFT):
    """FFT-bin edges (N_BANDS + 1 values) for log-spaced bands."""
    hz = F_MIN * (F_MAX / F_MIN) ** (np.arange(N_BANDS + 1) / N_BANDS)
    nb = n_fft // 2 + 1
    bins = np.round(hz * n_fft / float(sr)).astype(int)
    bins = np.clip(bins, 1, nb - 1)
    for i in range(1, len(bins)):
        if bins[i] <= bins[i - 1]:
            bins[i] = min(bins[i - 1] + 1, nb)
    return bins


class SpectrumAnalyzer:
    def __init__(self, sample_rate):
        self.sr = int(sample_rate) if sample_rate else 44100
        self.window = np.hanning(N_FFT).astype(np.float32)
        self.edges = band_edges(self.sr)
        self.tilt = (np.arange(N_BANDS) * 0.35).astype(np.float32)  # dB, compensates pink-ish spectra
        self._buf = np.zeros(0, dtype=np.float32)
        self._frames = []
        self._rms = []
        self.bands = np.zeros((0, N_BANDS), dtype=np.float32)
        self.envelope = None
        self.done = False
        self._lock = threading.Lock()
        self._prov = None
        self._prov_n = 0

    # -- streaming -----------------------------------------------------------------
    def feed(self, mono):
        mono = np.asarray(mono, dtype=np.float32)
        if mono.size == 0:
            return
        self._buf = np.concatenate([self._buf, mono]) if self._buf.size else mono
        if self._buf.size < N_FFT:
            return
        total = (self._buf.size - N_FFT) // HOP + 1
        start = 0
        while start < total:
            n = min(128, total - start)
            idx = np.arange(N_FFT)[None, :] + HOP * (start + np.arange(n))[:, None]
            raw = self._buf[idx]
            seg = raw * self.window
            spec = np.abs(np.fft.rfft(seg, axis=1)) / (N_FFT / 4.0)
            power = spec * spec
            cs = np.concatenate([np.zeros((n, 1), dtype=power.dtype), np.cumsum(power, axis=1)], axis=1)
            band_power = cs[:, self.edges[1:]] - cs[:, self.edges[:-1]]
            db = 10.0 * np.log10(band_power + 1e-12) + self.tilt
            v = np.clip((db - DB_FLOOR) / DB_SPAN, 0.0, 1.0)
            with self._lock:
                self._frames.append(v.astype(np.float32))
            self._rms.append(np.sqrt(np.mean(raw[:, :HOP] ** 2, axis=1)))
            start += n
            time.sleep(0.0008)   # let the interface thread breathe while a song is analysed
        self._buf = self._buf[total * HOP:]

    def _stack(self):
        with self._lock:
            if self._frames and not self.done:
                self.bands = np.concatenate(self._frames, axis=0)
                self._frames = [self.bands]

    @staticmethod
    def _moving_mean(x, win):
        """Centred moving average along axis 0 (edges padded)."""
        win = max(3, int(win) | 1)
        pad = win // 2
        xp = np.pad(x, ((pad, pad), (0, 0)), mode="edge")
        cs = np.cumsum(np.concatenate([np.zeros((1, x.shape[1]), dtype=xp.dtype), xp], axis=0), axis=0)
        return (cs[win:] - cs[:-win]) / float(win)

    def finish(self):
        """Normalise loudness and build the seek-bar envelope (heavy maths outside the lock, swap inside)."""
        self._stack()
        with self._lock:
            src = self.bands
        if src.shape[0] == 0:
            self.done = True
            return
        # whiten: bring every band to a similar working range so all of them react to the song
        p = np.percentile(src, 92, axis=0)
        shift = np.clip(0.70 - p, -0.25, 0.16)
        b = src + shift[None, :]
        b = np.clip((b - 0.10) * 1.18, 0.0, 1.0) ** 1.35
        # rhythm emphasis: compare every band with its own ~1.3 s average so beats / hits stand out
        # and lulls drop low (the visuals then move "on the beat" instead of floating at a constant height)
        mean = self._moving_mean(b, 40)
        punch = np.clip((b - mean) * 2.6 + 0.45, 0.0, 1.0)
        b = np.clip(0.55 * b + 0.50 * punch * np.sqrt(b), 0.0, 1.0).astype(np.float32)
        rms = np.concatenate(self._rms) if self._rms else np.zeros(1, dtype=np.float32)
        n = len(rms)
        bins = min(ENV_BINS, n)
        edges = np.linspace(0, n, bins + 1).astype(int)
        env = np.array([float(rms[a:max(c, a + 1)].max()) for a, c in zip(edges[:-1], edges[1:])], dtype=np.float32)
        ref = float(np.percentile(env, 98)) or 1.0
        env = np.clip(env / ref, 0.0, 1.0) ** 0.7
        with self._lock:
            self.bands = b
            self._frames = [b]
            self.envelope = env
            self.done = True

    # -- playback side ---------------------------------------------------------------
    def frame_at(self, pos_ms):
        """Return the band levels (list of floats) at a playback position, or None."""
        self._stack()
        n = self.bands.shape[0]
        if n == 0:
            return None
        x = (pos_ms / 1000.0 * self.sr - N_FFT / 2) / HOP
        if x <= 0:
            row = self.bands[0]
        else:
            i = int(x)
            if i >= n - 1:
                if i >= n and not self.done:
                    return None
                row = self.bands[n - 1]
            else:
                fr = x - i
                row = self.bands[i] * (1.0 - fr) + self.bands[i + 1] * fr
        if not self.done:
            row = self._provisional(row, n)
        return row.tolist()

    def _provisional(self, row, n):
        """While the song is still being analysed, level the bands with what was heard so far
        (the final analysis does the same over the whole song), so nothing jumps when it completes."""
        if n >= 40 and (self._prov is None or n - self._prov_n >= 120):
            self._prov = np.clip(0.70 - np.percentile(self.bands, 92, axis=0), -0.25, 0.16).astype(np.float32)
            self._prov_n = n
        if self._prov is None:
            return row
        b = np.clip((row + self._prov - 0.10) * 1.18, 0.0, 1.0) ** 1.35
        return b.astype(np.float32)
