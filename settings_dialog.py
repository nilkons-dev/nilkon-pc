"""NILKON settings: appearance (mode, colour/wave theme, backgrounds), visualizer, audio, library, about."""
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from PySide6.QtCore import Qt, QRectF, QPointF, QEvent, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont, QLinearGradient, QRadialGradient, QPen, QBrush
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QWidget, QStackedWidget, QAbstractButton,
                               QScrollArea, QFrame, QGridLayout, QLineEdit)

from appinfo import APP_NAME, APP_VERSION, APP_TAGLINE
from dialogs import GlassDialog, SHADOW
from panels import LogoMark
from icons import qicon, draw_icon
from theme import T, ACCENTS, ink, alpha
from widgets import GButton, GlassSlider, ToggleSwitch, ui_font, round_path, eyebrow, NOPEN, NOBRUSH, AA

BACKGROUNDS = [("aurora", "Aurora"), ("midnight", "Midnight"), ("deepspace", "Deep Space"), ("bluehaze", "Blue Haze"),
               ("superdark", "Super Dark")]
TILE = (124, 88)
GRID_COLS = 5
WAVE_STYLES = [("waves", "Flowing waves", "waves"), ("bars", "Spectrum bars", "pulse"), ("mirror", "Mirror bars", "eq")]


class SmoothScrollArea(QScrollArea):
    """Scroll area whose wheel works over *any* child (tiles, sliders...) and glides."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.verticalScrollBar().setValue(int(v)))
        self._target = 0

    def adopt(self):
        """Route wheel events of every descendant here (call after the content is built)."""
        self.viewport().installEventFilter(self)
        for w in self.widget().findChildren(QWidget):
            w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel:
            self.wheelEvent(ev)
            return True
        return super().eventFilter(obj, ev)

    def wheelEvent(self, e):
        bar = self.verticalScrollBar()
        dy = e.angleDelta().y()
        step = dy / 120.0 * 80.0 if dy else float(e.pixelDelta().y())
        base = self._target if self._anim.state() == QVariantAnimation.State.Running else bar.value()
        self._target = max(bar.minimum(), min(bar.maximum(), int(base - step)))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(self._target)
        self._anim.start()
        e.accept()


class Tile(QAbstractButton):
    """Selectable preview tile with a caption."""

    def __init__(self, label, painter, size=(132, 92), parent=None):
        super().__init__(parent)
        self._label = label
        self._painter = painter      # callable(QPainter, QRectF)
        self._sel = False
        self._hover = False
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_selected(self, on):
        if on != self._sel:
            self._sel = on
            self.update()

    def set_painter(self, fn):
        self._painter = fn
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        prev = QRectF(2, 2, w - 4, h - 4 - 24)
        clip = round_path(prev, 14)
        p.save()
        p.setClipPath(clip)
        self._painter(p, prev)
        p.restore()
        p.setBrush(NOBRUSH)
        if self._sel:
            p.setPen(QPen(T.c1, 2.2))
        else:
            p.setPen(QPen(ink(0.34 if self._hover else 0.16), 1))
        p.drawPath(round_path(prev.adjusted(0.5, 0.5, -0.5, -0.5), 14) if not self._sel else round_path(prev, 14))
        f = ui_font(12, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(ink(0.95 if self._sel else 0.62))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignmentFlag.AlignCenter, self._label)
        if self._sel:
            p.setPen(NOPEN)
            p.setBrush(T.c1)
            c = QPointF(prev.right() - 14, prev.top() + 14)
            p.drawEllipse(c, 9, 9)
            draw_icon(p, "check", QRectF(c.x() - 6, c.y() - 6, 12, 12), T.on_accent)


def paint_aurora_preview(p, r):
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor(7, 12, 30))
    g.setColorAt(1, QColor(4, 7, 18))
    p.fillRect(r, QBrush(g))
    for (fx, fy, rad, col) in ((0.2, 0.3, 0.7, T.t1), (0.85, 0.2, 0.55, T.t2), (0.55, 0.95, 0.7, T.t3)):
        rg = QRadialGradient(QPointF(r.left() + r.width() * fx, r.top() + r.height() * fy), r.width() * rad)
        rg.setColorAt(0, alpha(col, 0.55))
        rg.setColorAt(1, alpha(col, 0.0))
        p.fillRect(r, QBrush(rg))


def accent_painter(name):
    c1, c2, c3 = (QColor(x) for x in ACCENTS[name])

    def paint(p, r):
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(8, 12, 28))
        g.setColorAt(1, QColor(4, 7, 18))
        p.fillRect(r, QBrush(g))
        n = 14
        bw = r.width() / (n * 1.5)
        gr = QLinearGradient(r.left(), 0, r.right(), 0)
        gr.setColorAt(0, c1)
        gr.setColorAt(0.5, c2)
        gr.setColorAt(1, c3)
        p.setPen(NOPEN)
        p.setBrush(QBrush(gr))
        for i in range(n):
            import math
            v = 0.25 + 0.65 * abs(math.sin(i * 0.55 + 0.6)) * (0.6 + 0.4 * math.cos(i * 0.21))
            hh = r.height() * 0.62 * v
            x = r.left() + bw * 0.6 + i * bw * 1.5
            p.drawRoundedRect(QRectF(x, r.bottom() - 8 - hh, bw, hh), bw / 2, bw / 2)
    return paint


def wave_painter(style):
    import math

    def paint(p, r):
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor(8, 12, 28))
        g.setColorAt(1, QColor(4, 7, 18))
        p.fillRect(r, QBrush(g))
        gr = QLinearGradient(r.left(), 0, r.right(), 0)
        gr.setColorAt(0, T.t1)
        gr.setColorAt(0.5, T.t2)
        gr.setColorAt(1, T.t3)
        mid = r.center().y()
        if style == "waves":
            from PySide6.QtGui import QPainterPath
            for k, (amp, ph, a) in enumerate(((0.30, 0.0, 0.95), (0.20, 1.4, 0.55), (0.12, 2.8, 0.30))):
                path = QPainterPath()
                steps = 40
                for i in range(steps + 1):
                    x = r.left() + r.width() * i / steps
                    y = mid + math.sin(i / steps * math.pi * 2.6 + ph) * r.height() * amp
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                pen = QPen(QBrush(gr), 2.4 - k * 0.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setOpacity(a)
                p.setPen(pen)
                p.setBrush(NOBRUSH)
                p.drawPath(path)
            p.setOpacity(1.0)
        else:
            n = 18
            bw = r.width() / (n * 1.5)
            p.setPen(NOPEN)
            p.setBrush(QBrush(gr))
            for i in range(n):
                v = 0.2 + 0.7 * abs(math.sin(i * 0.5 + 0.4))
                hh = r.height() * 0.55 * v
                x = r.left() + bw * 0.6 + i * bw * 1.5
                if style == "mirror":
                    p.drawRoundedRect(QRectF(x, mid - hh / 2, bw, hh), bw / 2, bw / 2)
                else:
                    p.drawRoundedRect(QRectF(x, r.bottom() - 8 - hh, bw, hh), bw / 2, bw / 2)
    return paint


def pixmap_painter(pm, dimmed=True):
    def paint(p, r):
        if pm is None or pm.isNull():
            p.fillRect(r, QColor(10, 14, 30))
            return
        s = pm.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                      Qt.TransformationMode.SmoothTransformation)
        sx = max(0, (s.width() - int(r.width())) // 2)
        sy = max(0, (s.height() - int(r.height())) // 2)
        p.drawPixmap(r.toRect(), s, s.rect().adjusted(sx, sy, -sx, -sy))
        if dimmed:
            p.fillRect(r, QColor(3, 6, 16, 90))
    return paint


def custom_painter(has_image):
    def paint(p, r):
        p.fillRect(r, QColor(10, 15, 32) if T.dark else QColor(225, 232, 246))
        p.setPen(QPen(ink(0.35), 1.4, Qt.PenStyle.DashLine))
        p.setBrush(NOBRUSH)
        p.drawRoundedRect(r.adjusted(8, 8, -8, -8), 10, 10)
        draw_icon(p, "image", QRectF(r.center().x() - 12, r.center().y() - 12, 24, 24), ink(0.7))
    return paint


class SettingRow(QWidget):
    def __init__(self, title, desc, control, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("dlgHead")
        col.addWidget(t)
        if desc:
            d = QLabel(desc)
            d.setObjectName("dlgText")
            d.setWordWrap(True)
            col.addWidget(d)
        lay.addLayout(col, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingsDialog(GlassDialog):
    """host must provide: lib, engine, apply_setting(key), open_equalizer(), clear_recent(),
    reset_listen_counts(), pick_custom_background() -> bool, background_preview(name) -> QPixmap|None."""

    def __init__(self, parent, host, start_page=0):
        super().__init__(parent)
        self.host = host
        self.lib = host.lib
        self.s = host.lib.settings
        self._tg, self._sl, self._ch = {}, {}, {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + 28, SHADOW + 24, SHADOW + 28, SHADOW + 22)
        outer.setSpacing(14)

        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(qicon("settings", T.c1.lighter(115) if T.dark else T.c1.darker(115), 24).pixmap(24, 24))
        head.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        t = QLabel("Settings")
        t.setObjectName("dlgTitle")
        sub = QLabel("Make NILKON look and sound the way you like")
        sub.setObjectName("dlgSub")
        tv.addWidget(t)
        tv.addWidget(sub)
        head.addLayout(tv)
        head.addStretch(1)
        close = GButton("", "x", "flat", 16)
        close.clicked.connect(self.accept)
        head.addWidget(close)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(18)
        nav = QVBoxLayout()
        nav.setSpacing(4)
        self.pages = QStackedWidget()
        self.nav_btns = []
        for i, (label, icon, builder) in enumerate((
                ("Appearance", "palette", self._page_appearance), ("Visualizer", "waves", self._page_visual),
                ("Audio", "eq", self._page_audio), ("Playback", "play", self._page_playback),
                ("Online & Discord", "globe", self._page_online),
                ("Library", "library", self._page_library),
                ("About", "info", self._page_about))):
            b = GButton(label, icon, "nav", 18)
            b.setFixedWidth(168)
            b.clicked.connect(lambda _=False, ix=i: self._go(ix))
            nav.addWidget(b)
            self.nav_btns.append(b)
            self.pages.addWidget(self._scroll(builder()))
        nav.addStretch(1)
        body.addLayout(nav)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self._go(start_page)
        self._sync()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._sync_status)
        self._status_timer.start(1000)
        self._sync_status()
        self.setFixedSize(990, 700)

    # -- structure ---------------------------------------------------------------------
    @staticmethod
    def _scroll(widget):
        sc = SmoothScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.viewport().setAutoFillBackground(False)
        sc.setWidget(widget)
        sc.adopt()
        return sc

    def _go(self, i):
        self.pages.setCurrentIndex(i)
        for k, b in enumerate(self.nav_btns):
            b.set_active(k == i)

    @staticmethod
    def _page():
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 10, 8)
        lay.setSpacing(10)
        return w, lay

    @staticmethod
    def _section(lay, text):
        lay.addSpacing(6)
        lay.addWidget(eyebrow(text))

    def _set(self, key, value):
        self.s[key] = value
        self.host.apply_setting(key)
        self._sync()

    # -- small builders for the extra options ------------------------------------------
    def _toggle_row(self, lay, key, title, desc):
        t = ToggleSwitch()
        t.toggled.connect(lambda on, k=key: self._set(k, bool(on)))
        lay.addWidget(SettingRow(title, desc, t))
        self._tg[key] = t

    def _slider_row(self, lay, key, title, desc, lo, hi, fmt):
        sl = GlassSlider(Qt.Orientation.Horizontal, lo, hi)
        sl.setFixedWidth(220)
        val = QLabel("")
        val.setObjectName("dlgVal")
        val.setMinimumWidth(52)
        sl.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(sl)
        bl.addWidget(val)
        lay.addWidget(SettingRow(title, desc, box))
        self._sl[key] = (sl, val, fmt)

    def _choice_row(self, lay, key, title, desc, options):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        btns = {}
        for value, label in options:
            b = GButton(label, None, "chip")
            b.clicked.connect(lambda _=False, k=key, v=value: self._set(k, v))
            rl.addWidget(b)
            btns[value] = b
        lay.addWidget(SettingRow(title, desc, row))
        self._ch[key] = btns

    # -- pages -------------------------------------------------------------------------
    def _page_playback(self):
        w, lay = self._page()
        self._section(lay, "STARTING UP")
        self._toggle_row(lay, "resume_last", "Resume where I stopped", "Opens your last song, paused, at the same position.")
        self._choice_row(lay, "start_page", "Open on", "The page NILKON shows when it starts.", (("home", "Home"), ("online", "Online search")))
        self._section(lay, "PLAYING")
        self._toggle_row(lay, "auto_radio", "Keep playing similar songs", "After an online song, similar songs follow automatically.")
        self._slider_row(lay, "volume_step", "Volume step", "How much Ctrl + Up / Down changes the volume.", 1, 20, lambda v: f"{v}%")
        self._slider_row(lay, "seek_step", "Skip step", "How far Alt + Left / Right jumps inside a song.", 3, 60, lambda v: f"{v} s")
        self._section(lay, "SLEEP TIMER")
        self.sleep_btns = {}
        srow = QHBoxLayout()
        srow.setSpacing(8)
        for mins, label in ((0, "Off"), (15, "15 min"), (30, "30 min"), (45, "45 min"), (60, "1 hour"), (90, "1.5 hours")):
            b = GButton(label, None, "chip")
            b.clicked.connect(lambda _=False, mm=mins: (self.host.set_sleep_timer(mm), self._sync()))
            srow.addWidget(b)
            self.sleep_btns[mins] = b
        srow.addStretch(1)
        lay.addLayout(srow)
        n = QLabel("The music pauses by itself when the timer ends - handy at bedtime.")
        n.setObjectName("dlgText")
        n.setWordWrap(True)
        lay.addWidget(n)
        lay.addStretch(1)
        return w

    def _page_appearance(self):
        w, lay = self._page()
        self._section(lay, "MODE")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.mode_dark = GButton("Dark", "moon", "chip", 15)
        self.mode_light = GButton("Light", "sun", "chip", 15)
        self.mode_dark.clicked.connect(lambda: self._set("mode", "dark"))
        self.mode_light.clicked.connect(lambda: self._set("mode", "light"))
        row.addWidget(self.mode_dark)
        row.addWidget(self.mode_light)
        row.addStretch(1)
        lay.addLayout(row)

        self._section(lay, "COLOUR THEME  ·  UI ACCENT AND SOUND WAVES")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.accent_tiles = {}
        for i, name in enumerate(ACCENTS):
            tile = Tile(name, accent_painter(name), TILE)
            tile.clicked.connect(lambda _=False, n=name: self._set("accent", n))
            grid.addWidget(tile, i // GRID_COLS, i % GRID_COLS)
            self.accent_tiles[name] = tile
        grid.setColumnStretch(GRID_COLS, 1)
        lay.addLayout(grid)
        self.adaptive = ToggleSwitch()
        self.adaptive.toggled.connect(lambda v: self._set("adaptive", bool(v)))
        lay.addWidget(SettingRow("Adapt colours to album art",
                                 "Tint the interface and waves with the colours of the playing cover.", self.adaptive))

        self._section(lay, "BACKGROUND")
        bg = QGridLayout()
        bg.setSpacing(12)
        self.bg_tiles = {}
        for i, (key, label) in enumerate(BACKGROUNDS):
            if key == "aurora":
                painter = paint_aurora_preview
            else:
                painter = pixmap_painter(self.host.background_preview(key))
            tile = Tile(label, painter, TILE)
            tile.clicked.connect(lambda _=False, k=key: self._set("background", k))
            bg.addWidget(tile, i // GRID_COLS, i % GRID_COLS)
            self.bg_tiles[key] = tile
        n = len(BACKGROUNDS)
        self.custom_tile = Tile("Custom image", custom_painter(False), TILE)
        self.custom_tile.clicked.connect(self._pick_custom)
        bg.addWidget(self.custom_tile, n // GRID_COLS, n % GRID_COLS)
        bg.setColumnStretch(GRID_COLS, 1)
        lay.addLayout(bg)
        self.custom_note = QLabel("")
        self.custom_note.setObjectName("dlgText")
        lay.addWidget(self.custom_note)

        self.dim = GlassSlider(Qt.Orientation.Horizontal, 0, 90)
        self.dim.setFixedWidth(220)
        self.dim.valueChanged.connect(lambda v: self._set("bg_dim", int(v)))
        lay.addWidget(SettingRow("Image darkness", "Keeps text readable on bright pictures.", self.dim))
        self.blur = GlassSlider(Qt.Orientation.Horizontal, 0, 100)
        self.blur.setFixedWidth(220)
        self.blur.valueChanged.connect(lambda v: self._set("bg_blur", int(v)))
        lay.addWidget(SettingRow("Image blur", "Soften the picture for a frosted look.", self.blur))
        self._section(lay, "INTERFACE")
        self._toggle_row(lay, "title_song", "Song name in the window title", "Shows what is playing in the taskbar and title bar.")
        self._toggle_row(lay, "toasts", "Pop-up messages", "Small confirmations such as “Added to favourites”. Errors always show.")
        lay.addStretch(1)
        return w

    def _page_visual(self):
        w, lay = self._page()
        self._section(lay, "SOUND WAVE STYLE")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.wave_tiles = {}
        for key, label, _ in WAVE_STYLES:
            tile = Tile(label, wave_painter(key), (150, 96))
            tile.clicked.connect(lambda _=False, k=key: self._set("wave_style", k))
            row.addWidget(tile)
            self.wave_tiles[key] = tile
        row.addStretch(1)
        lay.addLayout(row)
        n = QLabel("The waves are computed from the real audio of the song you are playing.")
        n.setObjectName("dlgText")
        n.setWordWrap(True)
        lay.addWidget(n)

        self._section(lay, "SYNC")
        self.offset = GlassSlider(Qt.Orientation.Horizontal, -400, 400, bipolar=True)
        self.offset.setFixedWidth(260)
        self.offset.valueChanged.connect(lambda v: self._set("sync_offset", int(v)))
        self.offset_label = QLabel("0 ms")
        self.offset_label.setObjectName("dlgVal")
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.offset)
        bl.addWidget(self.offset_label)
        lay.addWidget(SettingRow("Wave timing", "If the waves feel early or late against the sound, nudge them here.", box))

        self._section(lay, "RESPONSE")
        self._slider_row(lay, "wave_gain", "Sensitivity", "How tall the waves grow for the same loudness.", 50, 170, lambda v: f"{v}%")
        self._slider_row(lay, "wave_smooth", "Smoothness", "Low = snappy and sharp, high = soft and flowing.", 0, 100, lambda v: f"{v}%")

        self._section(lay, "PERFORMANCE")
        self.reduced = ToggleSwitch()
        self.reduced.toggled.connect(lambda v: self._set("reduced_fx", bool(v)))
        lay.addWidget(SettingRow("Reduced effects", "Lower animation rate for older computers.", self.reduced))
        lay.addStretch(1)
        return w

    def _page_audio(self):
        w, lay = self._page()
        self._section(lay, "EQUALIZER")
        self.eq_state = QLabel("")
        self.eq_state.setObjectName("dlgText")
        lay.addWidget(self.eq_state)
        self.eq_toggle = ToggleSwitch()
        self.eq_toggle.toggled.connect(self._eq_toggled)
        lay.addWidget(SettingRow("Equalizer", "Applies to every song that has no equalizer of its own.", self.eq_toggle))
        btn = GButton("Open full equalizer", "eq", "primary", 17)
        btn.clicked.connect(self._open_eq)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._section(lay, "LOUDNESS")
        self.norm_toggle = ToggleSwitch()
        self.norm_toggle.setChecked(bool(self.s.get("normalize")))
        self.norm_toggle.toggled.connect(self._norm_toggled)
        lay.addWidget(SettingRow("Even out loudness", "Keeps quiet and loud songs at a similar volume. Takes effect the next time you open NILKON.", self.norm_toggle))
        tip = QLabel("Tip: use the ⋯ menu on any song and choose “Customize equalizer” to give that song its own sound.")
        tip.setObjectName("dlgText")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return w

    def _page_online(self):
        w, lay = self._page()
        self._section(lay, "DOWNLOADS")
        self.dl_dir = QLabel("")
        self.dl_dir.setObjectName("dlgText")
        self.dl_dir.setWordWrap(True)
        lay.addWidget(self.dl_dir)
        brow = QHBoxLayout()
        brow.setSpacing(10)
        b1 = GButton("Change folder…", "folder-plus", "glass", 16)
        b1.clicked.connect(self._choose_dir)
        b2 = GButton("Open folder", "library", "glass", 16)
        b2.clicked.connect(self.host.open_download_dir)
        brow.addWidget(b1)
        brow.addWidget(b2)
        brow.addStretch(1)
        lay.addLayout(brow)
        frow = QHBoxLayout()
        frow.setSpacing(10)
        self.fmt_btns = {}
        for key, label in (("mp3", "MP3"), ("m4a", "M4A (original quality)")):
            b = GButton(label, "download", "chip", 15)
            b.clicked.connect(lambda _=False, k=key: self._set("download_format", k))
            frow.addWidget(b)
            self.fmt_btns[key] = b
        frow.addStretch(1)
        lay.addLayout(frow)
        self.ff_note = QLabel("")
        self.ff_note.setObjectName("dlgText")
        self.ff_note.setWordWrap(True)
        lay.addWidget(self.ff_note)
        upd = GButton("Update music engine", "reset", "glass", 16)
        upd.clicked.connect(self.host.update_ytdlp)
        lay.addWidget(SettingRow("Music engine", "If online playback or downloads stop working, update the engine.", upd))

        self.ck_btns = {}
        crow = QHBoxLayout()
        crow.setSpacing(8)
        for key, label in (("", "Off"), ("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("brave", "Brave")):
            b = GButton(label, None, "chip")
            b.clicked.connect(lambda _=False, k=key: self._set("cookie_browser", k))
            crow.addWidget(b)
            self.ck_btns[key] = b
        crow.addStretch(1)
        ck_t = QLabel("Only if songs stop loading with a “verification / not a bot” message: choose the browser you "
                      "are signed in to, and NILKON reuses that sign-in. Close the browser first if it fails.")
        ck_t.setObjectName("dlgText")
        ck_t.setWordWrap(True)
        lay.addWidget(ck_t)
        lay.addLayout(crow)

        self._section(lay, "DISCORD RICH PRESENCE")
        self.dc_toggle = ToggleSwitch()
        self.dc_toggle.toggled.connect(lambda on: self._set("discord_enabled", bool(on)))
        lay.addWidget(SettingRow("Show what I'm listening to on Discord",
                                 "Appears as “Listening to NILKON” on your profile while a song plays.", self.dc_toggle))
        self.dc_id = QLineEdit()
        self.dc_id.setObjectName("dlgInput")
        self.dc_id.setPlaceholderText("Discord Application ID (numbers)")
        self.dc_id.setMaxLength(24)
        self.dc_id.setFixedWidth(260)
        self.dc_id.editingFinished.connect(self._id_edited)
        lay.addWidget(SettingRow("Application ID", "Paste the ID from your Discord developer application.", self.dc_id))
        self.dc_status = QLabel("")
        self.dc_status.setObjectName("dlgHead")
        self.dc_status.setWordWrap(True)
        lay.addWidget(self.dc_status)
        how = QLabel("Setup (one time, 1 minute):\n"
                     "1. Open discord.com/developers/applications and press “New Application”. Name it NILKON.\n"
                     "2. Copy the “Application ID” from General Information and paste it above.\n"
                     "3. Optional: Rich Presence → Art Assets → upload the NILKON logo with the key  nilkon.\n"
                     "4. Keep the Discord desktop app open. Streamed songs also show their cover art.")
        how.setObjectName("dlgText")
        how.setWordWrap(True)
        lay.addWidget(how)
        portal = GButton("Open Developer Portal", "link", "glass", 16)
        portal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.com/developers/applications")))
        lay.addWidget(portal, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return w

    def _page_library(self):
        w, lay = self._page()
        self._section(lay, "YOUR DATA")
        self.lib_stats = QLabel("")
        self.lib_stats.setObjectName("dlgText")
        self.lib_stats.setWordWrap(True)
        lay.addWidget(self.lib_stats)
        b1 = GButton("Clear recently played", "history", "glass", 16)
        b1.clicked.connect(self._clear_recent)
        b2 = GButton("Reset listening statistics", "reset", "glass", 16)
        b2.clicked.connect(self._reset_counts)
        lay.addWidget(SettingRow("Recently played", "Empties the history list on the Home page.", b1))
        lay.addWidget(SettingRow("Suggestions", "Forget how often you played songs and what you like, so suggestions (also Online > Made for you) start fresh.", b2))
        loc = QLabel(f"Library file: {self.lib.file}")
        loc.setObjectName("dlgFreq")
        loc.setWordWrap(True)
        lay.addWidget(loc)
        lay.addStretch(1)
        return w

    def _page_about(self):
        w, lay = self._page()
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(LogoMark(self.host.engine, 72))
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        f = name.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        name.setFont(f)
        tag = QLabel(f"{APP_TAGLINE}  ·  Version {APP_VERSION}")
        tag.setObjectName("dlgText")
        col.addWidget(name)
        col.addWidget(tag)
        top.addLayout(col, 1)
        lay.addLayout(top)
        lay.addSpacing(6)
        d = QLabel("NILKON is a fast, private desktop music player. Play the music you own, search and stream "
                   "millions of songs online as you type, build playlists, save favourites and download tracks for "
                   "offline listening - all in one clean, flat interface. No account is needed: your library, "
                   "playlists and listening history stay on this computer.")
        d.setObjectName("dlgText")
        d.setWordWrap(True)
        lay.addWidget(d)

        for title, items in (
            ("LISTEN", ("Live online search - results appear while you type, songs only",
                        "Stream instantly, keep playing similar songs automatically, or download for offline",
                        "Smart shuffle that never repeats a song until everyone has played",
                        "Resumes your last song and position the next time you open it")),
            ("SOUND", ("Studio 10-band equalizer with 24 presets, bass / treble tone controls and your own saved presets",
                       "Smart headroom keeps boosted songs clean, with a separate setting for any single song",
                       "Sound waves and seek bar drawn from the real spectrum of the song, beat by beat")),
            ("YOUR LIBRARY", ("Unlimited playlists with drag-and-drop ordering - local and online songs together",
                              "Favourites, recently played and a home page that suggests what you love most",
                              "Cover art, tags, rename and Recycle-Bin delete")),
            ("EXTRAS", ("Discord Rich Presence - friends see what you are listening to",
                        "Dark and light modes, colour themes and your own background picture",
                        "Built-in crash log for quick support"))):
            self._section(lay, title)
            for text in items:
                row = QHBoxLayout()
                row.setSpacing(10)
                ic = QLabel()
                ic.setPixmap(qicon("check", T.c1.lighter(120) if T.dark else T.c1.darker(115), 16).pixmap(16, 16))
                ic.setFixedWidth(18)
                lab = QLabel(text)
                lab.setObjectName("dlgText")
                lab.setWordWrap(True)
                row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
                row.addWidget(lab, 1)
                lay.addLayout(row)

        self._section(lay, "SHORTCUTS")
        k = QLabel("Space  play / pause\nCtrl + Right / Left  next / previous song\nCtrl + Up / Down  volume\n"
                   "Ctrl + E  equalizer      Ctrl + ,  settings      Ctrl + O  add files")
        k.setObjectName("dlgText")
        lay.addWidget(k)

        self._section(lay, "BUILT WITH")
        b = QLabel("Python · Qt for Python (PySide6) · VLC audio engine · yt-dlp · NumPy · miniaudio · mutagen · pypresence")
        b.setObjectName("dlgText")
        b.setWordWrap(True)
        lay.addWidget(b)
        loc = QLabel(f"Your data is stored in {self.lib.dir}")
        loc.setObjectName("dlgFreq")
        loc.setWordWrap(True)
        lay.addWidget(loc)
        note = QLabel("Online features use publicly available music data for personal listening. "
                      "You are responsible for following the terms of the services you use and local copyright law. "
                      "NILKON is not affiliated with any streaming service.")
        note.setObjectName("dlgFreq")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    # -- state sync --------------------------------------------------------------------
    def _sync(self):
        s = self.s
        self.mode_dark.set_active(s["mode"] != "light")
        self.mode_light.set_active(s["mode"] == "light")
        for n, t in self.accent_tiles.items():
            t.set_selected(n == s["accent"])
        for k, t in self.bg_tiles.items():
            t.set_selected(s["background"] == k)
        has_custom = bool(s["custom_bg"]) and Path(s["custom_bg"]).is_file()
        self.custom_tile.set_selected(s["background"] == "custom" and has_custom)
        self.custom_tile.set_painter(pixmap_painter(self.host.background_preview("custom")) if has_custom
                                     else custom_painter(False))
        self.custom_note.setText(("Custom: " + Path(s["custom_bg"]).name) if has_custom else
                                 "Click “Custom image” to use your own picture (PNG, JPG, WEBP).")
        for sl, key in ((self.dim, "bg_dim"), (self.blur, "bg_blur"), (self.offset, "sync_offset")):
            if sl.value() != s[key]:
                sl.setValue(s[key])
        self.offset_label.setText("%+d ms" % s["sync_offset"] if s["sync_offset"] else "0 ms")
        for k, t in self.wave_tiles.items():
            t.set_selected(s["wave_style"] == k)
            t.set_painter(wave_painter(k))
        for n, t in self.accent_tiles.items():
            t.update()
        self.adaptive.blockSignals(True)
        self.adaptive.setChecked(bool(s["adaptive"]))
        self.adaptive.blockSignals(False)
        self.reduced.blockSignals(True)
        self.reduced.setChecked(bool(s["reduced_fx"]))
        self.reduced.blockSignals(False)
        self.eq_toggle.blockSignals(True)
        self.eq_toggle.setChecked(bool(self.lib.eq["enabled"]))
        self.eq_toggle.blockSignals(False)
        self.eq_state.setText(f"Current preset: {self.lib.eq['preset']}")
        self.lib_stats.setText(f"{len(self.lib.tracks)} songs · {len(self.lib.playlists)} playlists · "
                               f"{len(self.lib.liked)} favourites · {len(self.lib.history)} in recently played")
        for k, t in self._tg.items():
            t.blockSignals(True)
            t.setChecked(bool(s[k]))
            t.blockSignals(False)
        for k, (sl, val, fmt) in self._sl.items():
            if sl.value() != s[k]:
                sl.blockSignals(True)
                sl.setValue(int(s[k]))
                sl.blockSignals(False)
            val.setText(fmt(int(s[k])))
        for k, btns in self._ch.items():
            for v, b in btns.items():
                b.set_active(s[k] == v)
        for mins, b in self.sleep_btns.items():
            b.set_active(mins == getattr(self.host, "sleep_minutes", 0))
        for k, b in self.ck_btns.items():
            b.set_active(k == s["cookie_browser"])
        for k, b in self.fmt_btns.items():
            b.set_active(s["download_format"] == k)
        self.dl_dir.setText(f"Saved to: {self.lib.download_dir()}")
        has_ff = self.host.ffmpeg_available()
        self.ff_note.setText("ffmpeg found - MP3 conversion and cover embedding are available." if has_ff else
                             "ffmpeg not found - run: pip install imageio-ffmpeg  (needed for MP3). M4A works without it.")
        self.dc_toggle.blockSignals(True)
        self.dc_toggle.setChecked(bool(s["discord_enabled"]))
        self.dc_toggle.blockSignals(False)
        if not self.dc_id.hasFocus() and self.dc_id.text() != s["discord_app_id"]:
            self.dc_id.setText(s["discord_app_id"])
        self.update()

    # -- actions -----------------------------------------------------------------------
    def _choose_dir(self):
        if self.host.choose_download_dir(self):
            self._sync()

    def _id_edited(self):
        text = "".join(ch for ch in self.dc_id.text() if ch.isdigit())[:24]
        self.dc_id.setText(text)
        if text != self.s["discord_app_id"]:
            self._set("discord_app_id", text)

    def _sync_status(self):
        try:
            self.dc_status.setText("Status: " + self.host.presence.status_text)
        except Exception:
            pass

    def _pick_custom(self):
        if self.host.pick_custom_background(self):
            self._sync()

    def _norm_toggled(self, on):
        self.s["normalize"] = bool(on)
        self.host.save_soon()

    def _eq_toggled(self, on):
        self.lib.eq["enabled"] = bool(on)
        self.host.global_eq_changed()
        self._sync()

    def _open_eq(self):
        self.accept()
        self.host.open_equalizer()

    def _clear_recent(self):
        self.host.clear_recent()
        self._sync()

    def _reset_counts(self):
        self.host.reset_listen_counts()
        self._sync()
