"""Painted visuals: vinyl turntable with tonearm, spectrum bars, flowing wave field, EQ curve."""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QSize
from PySide6.QtGui import (QPainter, QPainterPath, QColor, QBrush, QPen, QLinearGradient, QRadialGradient,
                           QConicalGradient, QFont, QFontMetrics)
from PySide6.QtWidgets import QWidget, QSizePolicy

from theme import T, alpha, white, ink, clamp, smoothstep
from widgets import ui_font, round_path, NOPEN, NOBRUSH, AA
from engine import N, EQ_FREQS


# ------------------------------------------------------------------------------------
def solve_arm_angle(pivot, length, center, target_dist):
    """Tonearm angle (deg, 0 = pointing straight down, + swings towards the left) whose
    tip is `target_dist` away from the record centre."""
    best, best_err = 0.0, 1e9
    a = -20.0
    while a <= 70.0:
        rad = math.radians(a)
        tx = pivot[0] - length * math.sin(rad)
        ty = pivot[1] + length * math.cos(rad)
        err = abs(math.hypot(tx - center[0], ty - center[1]) - target_dist)
        if err < best_err:
            best, best_err = a, err
        a += 0.25
    return best


def paint_vinyl(p, c, r, angle, cover, glow=0.0, detail=1.0):
    """Draw a vinyl record centred at QPointF c with radius r, rotated by `angle` degrees."""
    p.setPen(NOPEN)
    # soft coloured halo
    if glow > 0.001:
        hg = QRadialGradient(c, r * 1.35)
        hg.setColorAt(0.70, alpha(T.c1, 0.30 * glow))
        hg.setColorAt(1.0, alpha(T.c1, 0.0))
        p.setBrush(QBrush(hg))
        p.drawEllipse(c, r * 1.35, r * 1.35)
    # body
    body = QRadialGradient(c, r)
    body.setColorAt(0.0, QColor(30, 31, 40))
    body.setColorAt(0.45, QColor(14, 15, 21))
    body.setColorAt(1.0, QColor(4, 4, 8))
    p.setBrush(QBrush(body))
    p.drawEllipse(c, r, r)

    label_r = r * 0.37
    ring = QPainterPath()
    ring.addEllipse(c, r * 0.985, r * 0.985)
    hole = QPainterPath()
    hole.addEllipse(c, label_r, label_r)
    ring = ring.subtracted(hole)

    # grooves
    step = max(0.022, 0.026 / max(0.3, detail))
    k = 0
    rr = label_r + r * 0.05
    p.setBrush(NOBRUSH)
    while rr < r * 0.965:
        p.setPen(QPen(QColor(255, 255, 255, 7 + (k % 3) * 3), 0.7))
        p.drawEllipse(c, rr, rr)
        rr += r * step
        k += 1
    for frac in (0.52, 0.69, 0.83):  # track gaps
        p.setPen(QPen(QColor(0, 0, 0, 150), max(1.0, r * 0.012)))
        p.drawEllipse(c, r * frac, r * frac)

    # rotating texture so the spin is visible
    p.save()
    p.translate(c)
    p.rotate(angle)
    tex = QConicalGradient(c, 0)
    stops = [(0.00, 0), (0.05, 26), (0.11, 0), (0.30, 0), (0.36, 15), (0.42, 0),
             (0.61, 0), (0.67, 26), (0.74, 0), (0.90, 0), (0.95, 12), (1.0, 0)]
    for pos, a in stops:
        tex.setColorAt(pos, QColor(255, 255, 255, a))
    p.setPen(NOPEN)
    p.setBrush(QBrush(tex))
    p.translate(-c.x(), -c.y())
    p.drawPath(ring)
    p.restore()

    # fixed specular sheen (reflection does not rotate with the record)
    sheen = QConicalGradient(c, 38)
    for pos, a in [(0.0, 0), (0.025, 70), (0.08, 0), (0.48, 0), (0.525, 62), (0.58, 0), (1.0, 0)]:
        sheen.setColorAt(pos, QColor(255, 255, 255, a))
    p.setBrush(QBrush(sheen))
    p.drawPath(ring)

    # rim
    p.setBrush(NOBRUSH)
    p.setPen(QPen(QColor(255, 255, 255, 48), max(1.0, r * 0.012)))
    p.drawEllipse(c, r, r)

    # label
    p.save()
    p.translate(c)
    p.rotate(angle)
    clip = QPainterPath()
    clip.addEllipse(QPointF(0, 0), label_r, label_r)
    p.setClipPath(clip)
    if cover is not None and not cover.isNull():
        sw, sh = cover.width(), cover.height()
        s = min(sw, sh)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QRectF(-label_r, -label_r, label_r * 2, label_r * 2), cover,
                     QRectF((sw - s) / 2.0, (sh - s) / 2.0, s, s))
        shade = QRadialGradient(QPointF(0, 0), label_r)
        shade.setColorAt(0.6, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.setPen(NOPEN)
        p.setBrush(QBrush(shade))
        p.drawEllipse(QPointF(0, 0), label_r, label_r)
    else:
        lab = QConicalGradient(QPointF(0, 0), 0)
        lab.setColorAt(0.0, T.c1)
        lab.setColorAt(0.33, T.c2)
        lab.setColorAt(0.66, T.c3)
        lab.setColorAt(1.0, T.c1)
        p.setPen(NOPEN)
        p.setBrush(QBrush(lab))
        p.drawEllipse(QPointF(0, 0), label_r, label_r)
        hl = QRadialGradient(QPointF(0, -label_r * 0.35), label_r * 1.1)
        hl.setColorAt(0.0, QColor(255, 255, 255, 90))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl))
        p.drawEllipse(QPointF(0, 0), label_r, label_r)
        if label_r > 14:
            p.setPen(QPen(QColor(255, 255, 255, 120), max(1.0, label_r * 0.05), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i in range(3):
                a = math.radians(i * 120 + 90)
                p.drawLine(QPointF(math.cos(a) * label_r * 0.50, math.sin(a) * label_r * 0.50),
                           QPointF(math.cos(a) * label_r * 0.78, math.sin(a) * label_r * 0.78))
    p.setClipping(False)
    p.setBrush(NOBRUSH)
    p.setPen(QPen(QColor(0, 0, 0, 140), max(1.0, r * 0.01)))
    p.drawEllipse(QPointF(0, 0), label_r, label_r)
    p.setPen(QPen(QColor(255, 255, 255, 60), 1.0))
    p.drawEllipse(QPointF(0, 0), label_r * 0.96, label_r * 0.96)
    p.restore()

    # spindle
    sp = QRadialGradient(c - QPointF(r * 0.01, r * 0.01), r * 0.06)
    sp.setColorAt(0.0, QColor(250, 250, 255))
    sp.setColorAt(1.0, QColor(150, 156, 175))
    p.setPen(NOPEN)
    p.setBrush(QBrush(sp))
    p.drawEllipse(c, r * 0.05, r * 0.05)
    p.setBrush(QColor(12, 12, 18))
    p.drawEllipse(c, r * 0.018, r * 0.018)


# ------------------------------------------------------------------------------------
class Turntable(QWidget):
    """Glass platter + spinning record + animated tonearm."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cover = None
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        engine.tick.connect(self._tick)

    def sizeHint(self):
        return QSize(300, 300)

    def set_cover(self, pix):
        self.cover = pix
        self.update()

    def _tick(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        eng = self.engine
        s = float(min(self.width(), self.height()))
        ox = (self.width() - s) / 2.0
        oy = (self.height() - s) / 2.0
        p.translate(ox, oy)
        c = QPointF(0.41 * s, 0.55 * s)
        r = 0.355 * s

        # platter
        plat = QRadialGradient(c, r * 1.12)
        plat.setColorAt(0.0, ink(0.07))
        plat.setColorAt(0.92, ink(0.04))
        plat.setColorAt(1.0, ink(0.13))
        p.setPen(QPen(ink(0.22), 1.0))
        p.setBrush(QBrush(plat))
        p.drawEllipse(c, r * 1.1, r * 1.1)
        p.setPen(QPen(ink(0.08), 1.0))
        p.drawEllipse(c, r * 1.045, r * 1.045)

        paint_vinyl(p, c, r, eng.angle, self.cover, 0.5 * (0.4 + 0.6 * eng.play_t), 1.0)

        self._paint_arm(p, s, c, r)

    def _paint_arm(self, p, s, c, r):
        eng = self.engine
        pivot = (0.89 * s, 0.10 * s)
        length = 0.60 * s
        out = solve_arm_angle(pivot, length, (c.x(), c.y()), r * 0.94)
        inn = solve_arm_angle(pivot, length, (c.x(), c.y()), r * 0.42)
        rest = out - 17.0
        k = smoothstep(eng.arm_t)
        ang = rest + (out - rest) * k + (inn - out) * eng.progress() * k
        rad = math.radians(ang)
        ux, uy = -math.sin(rad), math.cos(rad)
        P = QPointF(*pivot)
        tip = QPointF(pivot[0] + ux * length, pivot[1] + uy * length)
        tail = QPointF(pivot[0] - ux * 0.11 * s, pivot[1] - uy * 0.11 * s)
        lift = 1.0 - k
        sh_off = QPointF(0.010 * s + 0.02 * s * lift, 0.014 * s + 0.03 * s * lift)

        # shadow
        p.setBrush(NOBRUSH)
        p.setPen(QPen(QColor(0, 0, 0, int(70 - 25 * lift)), 0.026 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(tail + sh_off, tip + sh_off)

        # counterweight + arm
        p.setPen(QPen(QColor(120, 126, 150), 0.040 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(tail, P)
        p.setPen(QPen(QColor(30, 32, 44), 0.040 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QPointF(tail.x() + ux * 0.02 * s, tail.y() + uy * 0.02 * s), QPointF(tail.x() + ux * 0.05 * s, tail.y() + uy * 0.05 * s))
        arm_grad = QLinearGradient(P, tip)
        arm_grad.setColorAt(0.0, QColor(238, 241, 252))
        arm_grad.setColorAt(1.0, QColor(160, 168, 192))
        p.setPen(QPen(QBrush(arm_grad), 0.024 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(P, tip)
        p.setPen(QPen(white(0.55), 0.007 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(P.x() - uy * 0.006 * s, P.y() + ux * 0.006 * s), QPointF(tip.x() - uy * 0.006 * s, tip.y() + ux * 0.006 * s))

        # headshell
        p.save()
        p.translate(tip)
        p.rotate(ang + 14.0)
        hs = QRectF(-0.019 * s, -0.012 * s, 0.038 * s, 0.062 * s)
        hg = QLinearGradient(hs.topLeft(), hs.bottomRight())
        hg.setColorAt(0.0, QColor(245, 247, 255))
        hg.setColorAt(1.0, QColor(130, 138, 165))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.setBrush(QBrush(hg))
        p.drawRoundedRect(hs, 0.008 * s, 0.008 * s)
        p.setPen(NOPEN)
        p.setBrush(alpha(T.c1, 0.55 + 0.45 * k))
        p.drawEllipse(QPointF(0, 0.046 * s), 0.008 * s, 0.008 * s)
        p.restore()

        # pivot base
        bg = QRadialGradient(P - QPointF(0.01 * s, 0.01 * s), 0.07 * s)
        bg.setColorAt(0.0, QColor(250, 251, 255))
        bg.setColorAt(1.0, QColor(110, 118, 145))
        p.setPen(QPen(white(0.5), 1))
        p.setBrush(QBrush(bg))
        p.drawEllipse(P, 0.048 * s, 0.048 * s)
        p.setPen(NOPEN)
        p.setBrush(QColor(28, 30, 42))
        p.drawEllipse(P, 0.020 * s, 0.020 * s)
        p.setBrush(T.c1)
        p.drawEllipse(P, 0.008 * s, 0.008 * s)


class MiniDisc(QWidget):
    """Small spinning record used in the player dock."""

    def __init__(self, engine, size=68, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cover = None
        self.setFixedSize(size, size)
        engine.tick.connect(self._tick)

    def set_cover(self, pix):
        self.cover = pix
        self.update()

    def _tick(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = min(self.width(), self.height()) / 2.0 - 4
        paint_vinyl(p, c, r, self.engine.angle, self.cover, 0.5 * self.engine.play_t, 0.5)


# ------------------------------------------------------------------------------------
def level_at(levels, f):
    """Linear interpolation of the N-band level list at fraction f (0..1)."""
    x = clamp(f) * (N - 1)
    i = int(x)
    j = min(N - 1, i + 1)
    return levels[i] + (levels[j] - levels[i]) * (x - i)


class Spectrum(QWidget):
    """Rounded spectrum bars with peak caps and a soft reflection."""

    def __init__(self, engine, bars=28, reflection=True, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.bars = bars
        self.reflection = reflection
        self.setMinimumHeight(56)
        engine.tick.connect(self._tick)

    def _tick(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        eng = self.engine
        w, h = float(self.width()), float(self.height())
        n = self.bars
        gap = 3.0
        bw = max(2.0, (w - gap * (n - 1)) / n)
        base_y = h * (0.74 if self.reflection else 0.96)
        max_h = base_y - 2
        up = QLinearGradient(0, base_y, 0, base_y - max_h)
        up.setColorAt(0.0, T.c2)
        up.setColorAt(0.65, T.c1)
        up.setColorAt(1.0, T.c3)
        brush = QBrush(up)
        refl = QLinearGradient(0, base_y, 0, h)
        refl.setColorAt(0.0, alpha(T.c2, 0.30))
        refl.setColorAt(1.0, alpha(T.c2, 0.0))
        rbrush = QBrush(refl)
        p.setPen(NOPEN)
        for i in range(n):
            f = i / float(n - 1)
            v = level_at(eng.levels, f)
            pk = level_at(eng.peaks, f)
            bh = max(2.0, v * max_h)
            x = i * (bw + gap)
            p.setBrush(brush)
            p.drawRoundedRect(QRectF(x, base_y - bh, bw, bh), bw / 2.0, bw / 2.0)
            if pk > 0.04:
                p.setBrush(ink(0.55 * eng.play_t + 0.1))
                p.drawRoundedRect(QRectF(x, base_y - pk * max_h - 4, bw, 2.2), 1.1, 1.1)
            if self.reflection:
                rh = min(h - base_y - 1, bh * 0.45)
                p.setBrush(rbrush)
                p.drawRoundedRect(QRectF(x, base_y + 2, bw, max(1.0, rh)), bw / 2.0, bw / 2.0)


class WaveField(QWidget):
    """Layered flowing sound waves; they swell with the music and flatten when paused."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setMinimumHeight(60)
        self.wave_style = "waves"   # waves | bars | mirror
        engine.tick.connect(self._tick)

    def set_wave_style(self, name):
        self.wave_style = name if name in ("waves", "bars", "mirror") else "waves"
        self.update()

    def _tick(self):
        if self.isVisible():
            self.update()

    def _paint_bars(self, p, mirror):
        eng = self.engine
        w, h = float(self.width()), float(self.height())
        n = max(16, int(w / 9.0))
        gap = 3.0
        bw = max(2.0, (w - gap * (n - 1)) / n)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, T.c1)
        grad.setColorAt(0.5, T.c2)
        grad.setColorAt(1.0, T.c3)
        brush = QBrush(grad)
        p.setPen(NOPEN)
        p.setBrush(brush)
        for i in range(n):
            f = i / (n - 1.0)
            v = level_at(eng.levels, f)
            win = 0.35 + 0.65 * math.sin(math.pi * f) ** 0.6
            if mirror:
                amp = max(2.0, v * win * h * 0.46)
                rect = QRectF(i * (bw + gap), h / 2.0 - amp, bw, amp * 2)
            else:
                amp = max(2.5, v * win * h * 0.92)
                rect = QRectF(i * (bw + gap), h - amp - 2, bw, amp)
            p.drawRoundedRect(rect, bw / 2.0, bw / 2.0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        eng = self.engine
        w, h = float(self.width()), float(self.height())
        if w < 10:
            return
        if self.wave_style != "waves":
            self._paint_bars(p, self.wave_style == "mirror")
            return
        mid = h / 2.0
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, alpha(T.c1, 0.0))
        grad.setColorAt(0.18, T.c1)
        grad.setColorAt(0.5, T.c2)
        grad.setColorAt(0.82, T.c3)
        grad.setColorAt(1.0, alpha(T.c3, 0.0))
        brush = QBrush(grad)
        step = 5.0
        count = int(w / step) + 1
        hist = eng.hist
        t = eng.t
        # Each layer shows the *actual* spectrum of the song, a few frames older than the last one,
        # so the outline swells on every kick and trails away behind it. Bass sits in the centre.
        for li, (lag, a, lw, scale) in enumerate(((0, 0.95, 2.4, 1.0), (3, 0.55, 1.7, 0.80),
                                                   (6, 0.34, 1.3, 0.62), (10, 0.22, 1.0, 0.46))):
            if len(hist) > lag:
                frame = hist[-1 - lag]
            else:
                frame = eng.levels
            amps = []
            for i in range(count):
                x = min(w, i * step)
                f = x / w
                d = abs(2.0 * f - 1.0)
                lv = level_at(frame, d)
                window = math.sin(math.pi * f) ** 0.75
                base = (lv ** 0.9) * scale * (h * 0.46) * window
                ripple = math.sin(f * 36.0 + t * 2.4 + li * 1.7) * 0.07 * base
                amps.append(max(0.8, base + ripple) if eng.play_t > 0.01 else 0.8)
            sm = [amps[0]] + [(amps[i - 1] + 2.0 * amps[i] + amps[i + 1]) * 0.25 for i in range(1, count - 1)] + [amps[-1]]
            top = QPainterPath()
            bottom = QPainterPath()
            for i in range(count):
                x = min(w, i * step)
                if i == 0:
                    top.moveTo(x, mid - sm[i])
                    bottom.moveTo(x, mid + sm[i])
                else:
                    top.lineTo(x, mid - sm[i])
                    bottom.lineTo(x, mid + sm[i])
            for path, op, width in ((top, a * 0.25, lw * 4.5), (top, a, lw), (bottom, a * 0.25, lw * 4.5), (bottom, a * 0.8, lw)):
                p.setBrush(NOBRUSH)
                p.setOpacity(op)
                p.setPen(QPen(brush, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
            if li == 0:
                fill = QPainterPath(top)
                for i in range(count - 1, -1, -1):
                    fill.lineTo(min(w, i * step), mid + sm[i])
                fill.closeSubpath()
                fg = QLinearGradient(0, 0, w, 0)
                fg.setColorAt(0.0, alpha(T.c1, 0.0))
                fg.setColorAt(0.3, alpha(T.c1, 0.22))
                fg.setColorAt(0.5, alpha(T.c2, 0.26))
                fg.setColorAt(0.7, alpha(T.c3, 0.22))
                fg.setColorAt(1.0, alpha(T.c3, 0.0))
                p.setOpacity(1.0)
                p.setPen(NOPEN)
                p.fillPath(fill, QBrush(fg))
        p.setOpacity(1.0)


# ------------------------------------------------------------------------------------
def draw_mini_bars(p, rect, engine, color, active, count=4):
    """Tiny animated equaliser used in track rows / queue (`active` = playing)."""
    n = count
    gap = 2.0
    bw = (rect.width() - gap * (n - 1)) / n
    p.setPen(NOPEN)
    p.setBrush(color)
    for i in range(n):
        if active:
            v = 0.25 + 0.75 * level_at(engine.levels, (i + 0.5) / n * 0.6 + 0.05)
            v = max(v, 0.25 + 0.2 * (0.5 + 0.5 * math.sin(engine.t * 6 + i * 1.7)))
        else:
            v = (0.35, 0.6, 0.45, 0.3)[i % 4]
        bh = max(2.0, v * rect.height())
        p.drawRoundedRect(QRectF(rect.left() + i * (bw + gap), rect.bottom() - bh, bw, bh), bw / 2, bw / 2)


class EqCurve(QWidget):
    """Interactive EQ response curve with a live spectrum behind it. Drag nodes to edit."""
    bandChanged = Signal(int, int)
    COL_W = 64
    RANGE = 20

    def __init__(self, engine, values, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.values = list(values)
        self.enabled = True
        self._drag = -1
        self._hover = -1
        self.setFixedSize(self.COL_W * len(EQ_FREQS), 168)
        self.setMouseTracking(True)
        engine.tick.connect(self._tick)

    def _tick(self):
        if self.isVisible():
            self.update()

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def _y(self, v):
        half = self.height() / 2.0 - 18
        return self.height() / 2.0 - (v / float(self.RANGE)) * half

    def _val_from_y(self, y):
        half = self.height() / 2.0 - 18
        v = (self.height() / 2.0 - y) / half * self.RANGE
        return int(round(max(-self.RANGE, min(self.RANGE, v))))

    def _node(self, i):
        return QPointF(self.COL_W * (i + 0.5), self._y(self.values[i]))

    def _near(self, pos):
        i = int(pos.x() // self.COL_W)
        return i if 0 <= i < len(self.values) else -1

    def mousePressEvent(self, e):
        i = self._near(e.position())
        if i >= 0 and e.button() == Qt.MouseButton.LeftButton:
            self._drag = i
            self._apply(e.position())

    def mouseMoveEvent(self, e):
        if self._drag >= 0:
            self._apply(e.position())
        else:
            self._hover = self._near(e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = -1

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def _apply(self, pos):
        v = self._val_from_y(pos.y())
        if v != self.values[self._drag]:
            self.values[self._drag] = v
            self.bandChanged.emit(self._drag, v)
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        w, h = float(self.width()), float(self.height())
        card = round_path(QRectF(0, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5), 16)
        p.fillPath(card, ink(0.05))
        p.setClipPath(card)
        # grid + dB labels
        f = ui_font(10, QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        p.setFont(f)
        for db in (-20, -10, 0, 10, 20):
            y = self._y(db)
            p.setPen(QPen(ink(0.18 if db == 0 else 0.07), 1, Qt.PenStyle.DashLine if db else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            p.setPen(ink(0.40))
            p.drawText(QPointF(8, y - 3), "%+d" % db if db else "0")
        # live spectrum
        eng = self.engine
        n = 48
        bw = w / n
        sp = QLinearGradient(0, h, 0, 0)
        sp.setColorAt(0.0, alpha(T.c2, 0.0))
        sp.setColorAt(1.0, alpha(T.c1, 0.30))
        p.setPen(NOPEN)
        p.setBrush(QBrush(sp))
        for i in range(n):
            v = level_at(eng.levels, i / float(n - 1))
            bh = v * h * 0.85
            p.drawRoundedRect(QRectF(i * bw + 1.5, h - bh, bw - 3, bh), 2, 2)
        # curve
        pts = [self._node(i) for i in range(len(self.values))]
        path = QPainterPath()
        path.moveTo(QPointF(0, pts[0].y()))
        path.lineTo(pts[0])
        ext = [pts[0]] + pts + [pts[-1]]
        for i in range(1, len(ext) - 2):
            p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0, p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0, p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)
        path.lineTo(QPointF(w, pts[-1].y()))
        mid = h / 2.0
        fillp = QPainterPath(path)
        fillp.lineTo(QPointF(w, mid))
        fillp.lineTo(QPointF(0, mid))
        fillp.closeSubpath()
        fg = QLinearGradient(0, 0, 0, h)
        fg.setColorAt(0.0, alpha(T.c1, 0.34))
        fg.setColorAt(0.5, alpha(T.c2, 0.04))
        fg.setColorAt(1.0, alpha(T.c3, 0.28))
        p.setOpacity(1.0 if self.enabled else 0.35)
        p.fillPath(fillp, QBrush(fg))
        lg = QLinearGradient(0, 0, w, 0)
        lg.setColorAt(0.0, T.c1)
        lg.setColorAt(0.5, T.c2)
        lg.setColorAt(1.0, T.c3)
        p.setBrush(NOBRUSH)
        p.setPen(QPen(alpha(T.c2, 0.28), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(QBrush(lg), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        for i, pt in enumerate(pts):
            hot = i in (self._hover, self._drag)
            p.setPen(NOPEN)
            p.setBrush(alpha(T.c1, 0.30 if hot else 0.14))
            p.drawEllipse(pt, 11 if hot else 8, 11 if hot else 8)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(pt, 4.6, 4.6)
            p.setBrush(T.c2)
            p.drawEllipse(pt, 2.2, 2.2)
        p.setOpacity(1.0)
        p.setClipping(False)
        p.setBrush(NOBRUSH)
        p.setPen(QPen(ink(0.16), 1))
        p.drawPath(card)
