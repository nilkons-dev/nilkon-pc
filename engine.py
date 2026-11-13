"""VisualEngine: one shared ~30 fps clock that drives every animated widget.

It owns the smoothed spectrum, the vinyl rotation, tonearm position, accent colour
and the playback-position estimate, so all visuals stay in sync with each other.
"""
import math
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

import audio_analysis as aa
from theme import T, clamp

N = aa.N_BANDS
EQ_FREQS = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]  # VLC's real band centres
SPIN_DPS = 200.0  # ~33 1/3 rpm


def band_center(i):
    return aa.F_MIN * (aa.F_MAX / aa.F_MIN) ** ((i + 0.5) / N)


def eq_gain_curve(values, preamp, enabled):
    """EQ gain in dB at each visual band (log-frequency interpolation)."""
    if not enabled:
        return [0.0] * N
    logs = [math.log(f) for f in EQ_FREQS]
    vals = list(values) + [0] * (len(EQ_FREQS) - len(values))
    out = []
    for i in range(N):
        lf = math.log(band_center(i))
        g = 0.0
        if lf <= logs[0]:
            g = vals[0]
        elif lf >= logs[-1]:
            g = vals[len(logs) - 1]
        else:
            for k in range(len(logs) - 1):
                if logs[k] <= lf <= logs[k + 1]:
                    t = (lf - logs[k]) / (logs[k + 1] - logs[k])
                    g = vals[k] + (vals[k + 1] - vals[k]) * t
                    break
        out.append(g + preamp)
    return out


def synth_levels(t, seed):
    """Deterministic, beat-like fake spectrum used until real analysis is available."""
    bpm = 88 + (seed % 56)
    beat = 60.0 / bpm
    ph = (t / beat) % 1.0
    kick = math.exp(-ph * 5.0)
    off = ((t / beat) + 0.5) % 1.0
    hat = math.exp(-off * 9.0)
    out = []
    for i in range(N):
        x = i / (N - 1.0)
        low = kick * math.exp(-((x - 0.08) / 0.16) ** 2) * 0.95
        mid = (0.42 + 0.22 * math.sin(t * 1.3 + seed * 0.01 + i * 0.7)) * math.exp(-((x - 0.45) / 0.34) ** 2)
        mid *= 0.65 + 0.35 * math.sin(t * 0.7 + x * 6.0)
        high = hat * math.exp(-((x - 0.85) / 0.22) ** 2) * 0.55 + 0.10 * abs(math.sin(t * 9.1 + i * 1.9)) * x
        v = low + mid * 0.85 + high + 0.10 * (1 - x)
        out.append(clamp(v))
    return out


class VisualEngine(QObject):
    tick = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.t = 0.0
        self.dt = 0.033
        self.levels = [0.0] * N
        self.peaks = [0.0] * N
        self.bass = 0.0
        self.energy = 0.0
        self.play_t = 0.0   # 0 paused .. 1 playing (eased)
        self.arm_t = 0.0    # tonearm lowered amount
        self.spin_v = 0.0   # deg/s
        self.angle = 0.0
        self.playing = False
        self.analysis = None
        self.gain = 1.0                 # wave sensitivity
        self.smooth = 0.5               # 0 snappy .. 1 smooth
        self.seed = 1
        self.duration_ms = 0
        self.reduced = False
        self.active = True
        self.offset_ms = 0
        self.eq_db = [0.0] * N
        self.hist = deque(maxlen=16)   # recent level frames (newest last) - used for trailing waves
        self._pos_ms = 0.0
        self._pos_stamp = time.perf_counter()
        self._last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(33)

    # -- inputs ----------------------------------------------------------------------
    def set_playing(self, playing):
        if playing != self.playing:
            self._pos_ms = self.position_ms()
            self._pos_stamp = time.perf_counter()
            self.playing = playing

    def set_position(self, ms):
        self._pos_ms = float(max(0, ms))
        self._pos_stamp = time.perf_counter()

    def sync_position(self, ms):
        """Follow the player's clock without visible jumps: small errors are blended in, big ones snap."""
        now = time.perf_counter()
        est = self.position_ms()
        err = ms - est
        if not self.playing or abs(err) > 450:
            self.set_position(ms)
        else:
            self._pos_ms = est + err * 0.25
            self._pos_stamp = now

    def position_ms(self):
        if self.playing:
            ms = self._pos_ms + (time.perf_counter() - self._pos_stamp) * 1000.0
        else:
            ms = self._pos_ms
        if self.duration_ms > 0:
            ms = min(ms, self.duration_ms)
        return ms

    def progress(self):
        return clamp(self.position_ms() / self.duration_ms) if self.duration_ms > 0 else 0.0

    def set_eq(self, values, preamp, enabled):
        self.eq_db = eq_gain_curve(values, preamp, enabled)

    def set_reduced(self, reduced):
        self.reduced = bool(reduced)
        self.timer.setInterval(66 if self.reduced else 33)

    # -- clock -----------------------------------------------------------------------
    def _on_timer(self):
        now = time.perf_counter()
        dt = min(0.1, max(0.001, now - self._last))
        self._last = now
        if not self.active:
            return
        self.dt = dt
        self.t += dt

        # eased play state, tonearm and vinyl speed
        step = dt * 3.0
        self.play_t = clamp(self.play_t + (step if self.playing else -step))
        arm_step = dt * 0.85
        self.arm_t = clamp(self.arm_t + (arm_step if self.playing else -arm_step * 1.3))
        spin_target = SPIN_DPS * clamp((self.arm_t - 0.55) / 0.45) if self.playing else 0.0
        rate = 1.8 if spin_target > self.spin_v else 0.9
        self.spin_v += (spin_target - self.spin_v) * min(1.0, dt * rate)
        self.angle = (self.angle + self.spin_v * dt) % 360.0

        # spectrum
        raw = None
        if self.playing and self.analysis is not None:
            raw = self.analysis.frame_at(self.position_ms() + self.offset_ms)
        if raw is None:
            raw = synth_levels(self.t, self.seed) if self.playing else [0.0] * N
        atk = min(1.0, dt * 28.0)
        dec = min(1.0, dt * (22.0 - 16.0 * self.smooth))
        total = 0.0
        for i in range(N):
            v = clamp(raw[i] * self.gain + self.eq_db[i] / aa.DB_SPAN) if self.playing else 0.0
            cur = self.levels[i]
            cur += (v - cur) * (atk if v > cur else dec)
            self.levels[i] = cur
            self.peaks[i] = max(cur, self.peaks[i] - dt * 0.45)
            total += cur
        self.energy = total / N
        self.hist.append(list(self.levels))
        self.bass = sum(self.levels[:5]) / 5.0

        # accent colours cross-fade towards the selected theme
        if not T.settled():
            T.step(min(1.0, dt * 4.0))
        self.tick.emit()
