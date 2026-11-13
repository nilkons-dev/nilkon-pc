"""Reusable liquid-glass widgets: background, panels, buttons, sliders, seek bar, toast."""
import math
import random

from PySide6.QtCore import (Qt, QPointF, QRectF, QSize, Signal, QVariantAnimation, QEasingCurve,
                            QTimer, QPropertyAnimation)
from PySide6.QtGui import (QPainter, QPainterPath, QColor, QBrush, QPen, QLinearGradient, QRadialGradient,
                           QFont, QFontMetrics, QPixmap)
from PySide6.QtWidgets import QWidget, QFrame, QAbstractButton, QGraphicsOpacityEffect, QLabel, QSizePolicy

from icons import draw_icon
from theme import T, alpha, ink, surface, clamp, text_baseline, FONT_FAMILIES

NOPEN = Qt.PenStyle.NoPen
NOBRUSH = Qt.BrushStyle.NoBrush
AA = QPainter.RenderHint.Antialiasing


def ui_font(px, weight=QFont.Weight.Medium):
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def round_path(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def style_menu(menu):
    """Frameless translucent menu so the rounded corners from the stylesheet show."""
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return menu


# ------------------------------------------------------------------------------------
class AuroraBackground(QWidget):
    """Window backdrop: deep gradient with a still colour glow (no animation).

    Optionally shows an image (built-in or custom) dimmed/blurred underneath.
    """

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        # static colour glow: fx, fy, radius, colour index
        self.glow = [(0.12, 0.18, 0.46, 0), (0.86, 0.14, 0.40, 1), (0.50, 0.92, 0.50, 2), (0.92, 0.78, 0.38, 0),
                     (0.08, 0.84, 0.36, 1), (0.52, 0.42, 0.30, 2), (0.30, 0.55, 0.26, 1)]
        self._img = None
        self._img_cache = None
        self._img_key = None
        self._img_id = 0
        self._base = None
        self._base_key = None
        self.orb_scale = 1.0
        self._dim = 0.55
        self._blur = 0

    def set_background(self, pixmap, dim=55, blur=0):
        """pixmap=None -> animated aurora only."""
        self._img = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._img_id += 1
        self._dim = max(0.0, min(0.9, dim / 100.0))
        self._blur = max(0, min(100, int(blur)))
        self._img_key = None
        self.update()

    def _scaled_image(self):
        w, h = self.width(), self.height()
        key = (w, h, self._blur)
        if self._img_key != key or self._img_cache is None:
            s = self._img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            s = s.copy(max(0, (s.width() - w) // 2), max(0, (s.height() - h) // 2), w, h)
            if self._blur > 0:
                f = 1.0 + self._blur / 100.0 * 22.0
                small = s.scaled(max(8, int(w / f)), max(8, int(h / f)), Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                s = small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._img_cache, self._img_key = s, key
        return self._img_cache

    def _base_pixmap(self):
        """The whole backdrop (gradient, picture, soft colour glow, vignette) - static, drawn once per size/theme."""
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        dark = T.dark
        key = (w, h, round(dpr, 2), dark, self._img_id, round(self._dim, 3), self._blur,
               T.c1.rgb(), T.c2.rgb(), T.c3.rgb(), round(self.orb_scale, 2))
        if self._base_key != key or self._base is None:
            pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            q = QPainter(pm)
            q.setRenderHint(AA)
            q.fillRect(QRectF(0, 0, w, h), QColor(8, 10, 15) if dark else QColor(236, 240, 247))
            if self._img is not None:
                q.drawPixmap(0, 0, self._scaled_image())
                q.fillRect(QRectF(0, 0, w, h), surface(self._dim if dark else self._dim * 0.7))
            q.end()
            self._base, self._base_key = pm, key
        return self._base

    def paintEvent(self, _event):
        if self.width() < 2 or self.height() < 2:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self._base_pixmap())
        p.end()


# ------------------------------------------------------------------------------------
def paint_glass(p, r, rad, tint=0.0):
    """Flat card surface: one solid fill and a hairline border (follows the theme mode)."""
    rad = min(rad, 14)
    path = round_path(r, rad)
    if T.dark:
        p.fillPath(path, QColor(14, 17, 24, 236))
        edge = QColor(255, 255, 255, 22)
    else:
        p.fillPath(path, QColor(255, 255, 255, 238))
        edge = QColor(15, 23, 42, 34)
    p.setBrush(NOBRUSH)
    p.setPen(QPen(edge, 1.0))
    p.drawPath(path)


# ------------------------------------------------------------------------------------
class GlassPanel(QFrame):
    """Frosted liquid-glass surface: tint, sheen, specular edge and a lit border."""

    def __init__(self, radius=24, tint=0.66, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._tint = tint
        self._cache = None
        self._cache_key = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return
        dpr = self.devicePixelRatioF()
        key = (w, h, round(dpr, 2), self._radius, self._tint, T.dark, T.c1.rgb(), T.c3.rgb())
        if key != self._cache_key:
            pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(AA)
            paint_glass(q, QRectF(0, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._tint)
            q.end()
            self._cache, self._cache_key = pm, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()


# ------------------------------------------------------------------------------------
class GButton(QAbstractButton):
    """Custom-painted button. kinds: primary, glass, ghost, round, flat, nav, chip, play."""

    def __init__(self, text="", icon=None, kind="glass", icon_size=18, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._kind = kind
        self._isz = icon_size
        self._hover = 0.0
        self._active = False
        self._font = ui_font(13, QFont.Weight.DemiBold)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setText(text)
        if kind == "play":
            self.setFixedSize(72, 72)
        elif kind in ("round", "flat"):
            self.setFixedSize(40, 40)
        elif kind == "chip":
            self._font = ui_font(12, QFont.Weight.DemiBold)

    def _on_anim(self, v):
        self._hover = float(v)
        self.update()

    def _go(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, e):
        self._go(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._go(0.0)
        super().leaveEvent(e)

    def set_icon(self, name):
        if name != self._icon:
            self._icon = name
            self.update()

    def set_active(self, on):
        if on != self._active:
            self._active = on
            self.update()

    def sizeHint(self):
        k = self._kind
        if k == "play":
            return QSize(72, 72)
        if k in ("round", "flat"):
            return QSize(40, 40)
        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(self.text()) if self.text() else 0
        iw = (self._isz + (8 if self.text() else 0)) if self._icon else 0
        if k == "nav":
            return QSize(tw + iw + 40, 44)
        if k == "chip":
            return QSize(tw + iw + 26, 32)
        return QSize(tw + iw + 38, 42)

    # -- painting --------------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        h = self._hover
        down = self.isDown()
        k = self._kind
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if down:
            c = r.center()
            p.translate(c)
            p.scale(0.965, 0.965)
            p.translate(-c)
        if k == "play":
            self._paint_play(p, r, h)
            return
        radius = r.height() / 2.0 if k in ("chip", "round", "flat", "ghost") else 10.0
        path = round_path(r, radius)
        fg = ink(0.92)
        active = self._active or (self.isCheckable() and self.isChecked())

        if k == "primary":
            p.fillPath(path, T.c1.lighter(100 + int(12 * h)))
            fg = T.on_accent
        elif k in ("glass", "round", "chip"):
            if active:
                p.fillPath(path, alpha(T.c1, 0.18 + 0.07 * h))
                p.setPen(QPen(alpha(T.c1, 0.65), 1))
                fg = T.c1.lighter(125) if T.dark else T.c1.darker(120)
            else:
                p.fillPath(path, ink(0.05 + 0.06 * h))
                p.setPen(QPen(ink(0.13 + 0.10 * h), 1))
            p.setBrush(NOBRUSH)
            p.drawPath(path)
        elif k == "flat":
            if h > 0.01:
                p.fillPath(path, ink(0.10 * h))
            if active:
                fg = T.c1.lighter(120) if T.dark else T.c1.darker(115)
            else:
                fg = ink(0.62 + 0.34 * h)
        elif k == "ghost":
            if h > 0.01:
                p.fillPath(path, ink(0.10 * h))
            fg = ink(0.70 + 0.25 * h)
        elif k == "nav":
            if active:
                p.fillPath(path, alpha(T.c1, 0.13 + 0.03 * h))
                p.setPen(NOPEN)
                p.setBrush(T.c1)
                p.drawRoundedRect(QRectF(r.left() + 2, r.center().y() - r.height() * 0.26, 3.2, r.height() * 0.52), 1.6, 1.6)
                fg = ink(0.98)
            else:
                if h > 0.01:
                    p.fillPath(path, ink(0.06 * h))
                fg = ink(0.62 + 0.30 * h)

        # contents
        text = self.text()
        has_icon = bool(self._icon)
        fm = QFontMetrics(self._font)
        isz = self._isz
        tw = fm.horizontalAdvance(text) if text else 0
        gap = 9 if (text and has_icon) else 0
        total = (isz if has_icon else 0) + gap + tw
        if k == "nav":
            x = r.left() + 18
        else:
            x = r.center().x() - total / 2.0
        if has_icon:
            icol = QColor(fg)
            if k == "nav" and active:
                icol = T.c1.lighter(115) if T.dark else T.c1.darker(115)
            draw_icon(p, self._icon, QRectF(x, r.center().y() - isz / 2.0, isz, isz), icol)
            x += isz + gap
        if text:
            p.setFont(self._font)
            p.setPen(fg)
            avail = r.right() - x - 8
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(max(10, avail)))
            p.drawText(QPointF(x, text_baseline(fm, r.top(), r.height())), shown)
        if k == "flat" and active:
            p.setPen(NOPEN)
            p.setBrush(T.c1)
            p.drawEllipse(QPointF(r.center().x(), r.bottom() - 2.5), 1.8, 1.8)

    def _paint_play(self, p, r, h):
        c = r.center()
        rad = 26.0 + 1.0 * h
        p.setPen(NOPEN)
        p.setBrush(T.c1.lighter(100 + int(10 * h)))
        p.drawEllipse(c, rad, rad)
        if self._icon:
            isz = 26.0
            off = 1.5 if self._icon == "play" else 0.0
            draw_icon(p, self._icon, QRectF(c.x() - isz / 2 + off, c.y() - isz / 2, isz, isz), T.on_accent)


# ------------------------------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on)
        self.toggled.connect(self._go)

    def _on(self, v):
        self._t = float(v)
        self.update()

    def _go(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked):
        super().setChecked(checked)
        self._t = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = round_path(r, r.height() / 2)
        p.fillPath(path, ink(0.14))
        if self._t > 0.01:
            p.setOpacity(self._t)
            p.fillPath(path, T.c1)
            p.setOpacity(1.0)
        p.setBrush(NOBRUSH)
        p.setPen(QPen(ink(0.30), 1))
        p.drawPath(path)
        kr = r.height() / 2 - 3
        kx = r.left() + r.height() / 2 + (r.width() - r.height()) * self._t
        p.setPen(NOPEN)
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawEllipse(QPointF(kx, r.center().y()), kr, kr)


# ------------------------------------------------------------------------------------
class GlassSlider(QWidget):
    """Slider with glowing fill. `valueChanged` fires only for user input; setValue is silent."""
    valueChanged = Signal(int)
    sliderPressed = Signal()
    sliderReleased = Signal()

    def __init__(self, orientation=Qt.Orientation.Horizontal, minimum=0, maximum=100, bipolar=False, parent=None):
        super().__init__(parent)
        self._o = orientation
        self._min = minimum
        self._max = maximum
        self._v = minimum
        self._bipolar = bipolar
        self._drag = False
        self._hover = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        if orientation == Qt.Orientation.Horizontal:
            self.setMinimumHeight(24)
        else:
            self.setMinimumWidth(30)

    def value(self):
        return self._v

    def setValue(self, v):
        v = int(max(self._min, min(self._max, v)))
        if v != self._v:
            self._v = v
            self.update()

    def setRange(self, lo, hi):
        self._min, self._max = lo, hi
        self.setValue(self._v)

    def isSliderDown(self):
        return self._drag

    def _geom(self):
        pad = 11.0
        if self._o == Qt.Orientation.Horizontal:
            return pad, self.width() - pad
        return self.height() - pad, pad  # vertical: value grows upward

    def _pos_of(self, v):
        a, b = self._geom()
        f = (v - self._min) / float(max(1, self._max - self._min))
        return a + (b - a) * f

    def _value_at(self, pt):
        a, b = self._geom()
        coord = pt.x() if self._o == Qt.Orientation.Horizontal else pt.y()
        f = (coord - a) / (b - a) if b != a else 0.0
        return int(round(self._min + clamp(f) * (self._max - self._min)))

    def _set_user(self, v):
        v = int(max(self._min, min(self._max, v)))
        if v != self._v:
            self._v = v
            self.update()
            self.valueChanged.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self.sliderPressed.emit()
            self._set_user(self._value_at(e.position()))
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set_user(self._value_at(e.position()))

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.sliderReleased.emit()
            self.update()

    def mouseDoubleClickEvent(self, e):
        if self._bipolar:
            self._set_user(0)

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() > 0 else -1
        span = self._max - self._min
        self._set_user(self._v + step * (1 if span <= 40 else 5))
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._set_user(self._v - 1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._set_user(self._v + 1)
        else:
            super().keyPressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        if not self.isEnabled():
            p.setOpacity(0.4)
        horiz = self._o == Qt.Orientation.Horizontal
        gw = 6.0
        if horiz:
            groove = QRectF(11, self.height() / 2 - gw / 2, self.width() - 22, gw)
        else:
            groove = QRectF(self.width() / 2 - gw / 2, 11, gw, self.height() - 22)
        p.fillPath(round_path(groove, gw / 2), ink(0.14))
        pos = self._pos_of(self._v)
        origin = self._pos_of(0 if self._bipolar else self._min)
        lo, hi = (min(pos, origin), max(pos, origin))
        if horiz:
            fill = QRectF(lo, groove.top(), max(0.5, hi - lo), gw)
            grad = QLinearGradient(groove.left(), 0, groove.right(), 0)
        else:
            fill = QRectF(groove.left(), lo, gw, max(0.5, hi - lo))
            grad = QLinearGradient(0, groove.bottom(), 0, groove.top())
        grad.setColorAt(0.0, T.c1)
        grad.setColorAt(1.0, T.c2)
        if self._bipolar:
            # tick at zero
            p.setPen(QPen(ink(0.35), 1))
            if horiz:
                p.drawLine(QPointF(origin, groove.top() - 3), QPointF(origin, groove.bottom() + 3))
            else:
                p.drawLine(QPointF(groove.left() - 3, origin), QPointF(groove.right() + 3, origin))
        glow = QRectF(fill).adjusted(-1.5, -1.5, 1.5, 1.5)
        p.fillPath(round_path(glow, 4.5), alpha(T.c1, 0.22))
        p.fillPath(round_path(fill, gw / 2), QBrush(grad))
        kc = QPointF(pos, self.height() / 2) if horiz else QPointF(self.width() / 2, pos)
        kr = 8.0 if (self._hover or self._drag) else 7.0
        sh = QRadialGradient(kc + QPointF(0, 1.5), kr + 5)
        sh.setColorAt(0.5, QColor(0, 0, 0, 90))
        sh.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(NOPEN)
        p.setBrush(QBrush(sh))
        p.drawEllipse(kc + QPointF(0, 1.5), kr + 5, kr + 5)
        kg = QLinearGradient(kc.x(), kc.y() - kr, kc.x(), kc.y() + kr)
        kg.setColorAt(0.0, QColor(255, 255, 255))
        kg.setColorAt(1.0, QColor(214, 220, 238))
        p.setBrush(QBrush(kg))
        p.drawEllipse(kc, kr, kr)
        p.setBrush(T.c1)
        p.drawEllipse(kc, kr * 0.32, kr * 0.32)


# ------------------------------------------------------------------------------------
class SeekBar(QWidget):
    """Waveform progress bar (real loudness envelope when available)."""
    seekStarted = Signal()
    seekFinished = Signal(int)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._max = 0
        self._v = 0
        self._drag = False
        self._hover = -1.0
        self.envelope = None
        self._env_fade = 0.0
        self._fb = None
        self._fb_seed = None
        self.setMouseTracking(True)
        self.setMinimumHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        engine.tick.connect(self._tick)

    def _tick(self):
        if not self.isVisible():
            return
        animating = False
        if self.envelope is not None and self._env_fade < 1.0:
            self._env_fade = min(1.0, self._env_fade + 0.05)
            animating = True
        if self.engine.playing or animating:
            self.update()

    def _fallback(self):
        """Smooth, song-specific wave shown until (or instead of) the analysed loudness envelope."""
        seed = self.engine.seed
        if self._fb_seed != seed or self._fb is None:
            rnd = random.Random(seed * 7919 + 13)
            a, b, c = rnd.uniform(1.6, 3.4), rnd.uniform(4.5, 8.0), rnd.uniform(11.0, 19.0)
            p1, p2, p3 = (rnd.uniform(0, 6.28) for _ in range(3))
            n = 240
            out = []
            for i in range(n):
                f = i / float(n)
                v = 0.52 + 0.26 * math.sin(f * 6.283 * a + p1) + 0.16 * math.sin(f * 6.283 * b + p2) \
                    + 0.07 * math.sin(f * 6.283 * c + p3) + rnd.uniform(-0.05, 0.05)
                out.append(max(0.16, min(1.0, v)))
            self._fb, self._fb_seed = out, seed
        return self._fb

    def set_envelope(self, env):
        self.envelope = env
        self._env_fade = 0.0
        self.update()

    def setRange(self, lo, hi):
        self._max = max(0, hi)
        self.update()

    def setValue(self, v):
        if not self._drag:
            self._v = v
            self.update()

    def value(self):
        return self._v

    def _frac(self):
        return clamp(self._v / self._max) if self._max > 0 else 0.0

    def _from_x(self, x):
        return int(clamp((x - 4) / max(1.0, self.width() - 8)) * self._max)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._max > 0:
            self._drag = True
            self.seekStarted.emit()
            self._v = self._from_x(e.position().x())
            self.update()

    def mouseMoveEvent(self, e):
        self._hover = e.position().x()
        if self._drag:
            self._v = self._from_x(e.position().x())
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.seekFinished.emit(self._v)
            self.update()

    def leaveEvent(self, e):
        self._hover = -1.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        w, h = self.width(), self.height()
        frac = self._frac()
        env = self.envelope if (self.envelope is not None and len(self.envelope) >= 8) else None
        fb = self._fallback()
        px = 4 + (w - 8) * frac
        step = 5.0
        n = max(8, int((w - 8) / step))
        bw = 3.0
        maxh = h - 6
        fade = self._env_fade if env is not None else 0.0
        eng = self.engine
        pulse = eng.bass * eng.play_t
        breathe = eng.t * 2.2
        g = QLinearGradient(4, 0, w - 4, 0)
        g.setColorAt(0, T.c1)
        g.setColorAt(1, T.c2)
        played_brush = QBrush(g)
        idle_brush = QBrush(ink(0.24))
        p.setPen(NOPEN)
        for i in range(n):
            f = i / float(n)
            v = fb[min(len(fb) - 1, int(f * len(fb)))]
            if env is not None:
                v = v * (1.0 - fade) + float(env[min(len(env) - 1, int(f * len(env)))]) * fade
            else:
                v *= 0.55 + 0.45 * (0.5 + 0.5 * math.sin(breathe + i * 0.35)) * eng.play_t + 0.45 * (1 - eng.play_t)
            bh = max(3.0, 4 + v * (maxh - 4))
            x = 4 + i * step
            near = abs((x + bw / 2) - px)
            if near < 18:
                bh += (1 - near / 18.0) * (3 + 6 * pulse)
            bh = min(bh, maxh)
            p.setBrush(played_brush if x + bw / 2 <= px else idle_brush)
            p.drawRoundedRect(QRectF(x, h / 2 - bh / 2, bw, bh), 1.5, 1.5)
        if self._hover >= 0 and not self._drag:
            p.setBrush(ink(0.5))
            p.drawRect(QRectF(self._hover - 0.5, 4, 1, h - 8))
        # playhead
        p.setPen(NOPEN)
        halo = QRadialGradient(QPointF(px, h / 2), 13)
        halo.setColorAt(0.3, alpha(T.c1, 0.55))
        halo.setColorAt(1.0, alpha(T.c1, 0.0))
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(px, h / 2), 13, 13)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(px, h / 2), 5.5 if (self._drag or self._hover >= 0) else 4.5,
                      5.5 if (self._drag or self._hover >= 0) else 4.5)


# ------------------------------------------------------------------------------------
class Toast(QWidget):
    """Small glass pill that fades in/out above the player dock."""

    def __init__(self, parent):
        super().__init__(parent)
        self._text = ""
        self._font = ui_font(13, QFont.Weight.DemiBold)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text, ms=2400):
        self._text = text
        fm = QFontMetrics(self._font)
        self.setFixedSize(fm.horizontalAdvance(text) + 56, 40)
        par = self.parentWidget()
        if par is not None:
            self.move((par.width() - self.width()) // 2, par.height() - 150)
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setDuration(180)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(380)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = round_path(r, r.height() / 2)
        p.fillPath(path, QColor(8, 14, 30, 240) if T.dark else QColor(255, 255, 255, 245))
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(255, 255, 255, 40))
        g.setColorAt(1, QColor(255, 255, 255, 6))
        p.fillPath(path, QBrush(g))
        p.setBrush(NOBRUSH)
        p.setPen(QPen(ink(0.28), 1))
        p.drawPath(path)
        p.setPen(NOPEN)
        p.setBrush(T.c1)
        p.drawEllipse(QPointF(r.left() + 20, r.center().y()), 4, 4)
        p.setFont(self._font)
        p.setPen(ink(0.95))
        fm = QFontMetrics(self._font)
        p.drawText(QPointF(r.left() + 34, text_baseline(fm, r.top(), r.height())), self._text)


# ------------------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """Single-line label that shortens long text with an ellipsis instead of growing."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)
        self._elide()

    def set_full_text(self, text):
        self._full = text
        self.setToolTip(text if text else "")
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = QFontMetrics(self.font())
        QLabel.setText(self, fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(10, self.width())))


def eyebrow(text, object_name="eyebrow"):
    """Small spaced-out caption label."""
    lab = QLabel(text)
    lab.setObjectName(object_name)
    f = lab.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
    lab.setFont(f)
    return lab
