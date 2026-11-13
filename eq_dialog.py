"""Glass equalizer window: presets, draggable response curve, preamp and 10 band sliders.

Can edit the global equalizer or an override that belongs to a single song.
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QWidget, QFrame, QMenu

from dialogs import GlassDialog, SHADOW, ask_text, notice
from engine import EQ_FREQS
from icons import qicon
from theme import T
from visuals import EqCurve
from widgets import GButton, GlassSlider, ToggleSwitch, style_menu

EQ_PRESETS = {
    "Flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass Boost": [8, 7, 5, 2, 0, 0, 1, 2, 2, 2],
    "Bass Reducer": [-7, -6, -4, -1, 0, 0, 0, 0, 0, 0],
    "Treble Boost": [0, 0, 0, 1, 2, 4, 6, 7, 8, 8],
    "Treble Reducer": [0, 0, 0, 0, 0, -2, -4, -6, -8, -8],
    "Vocal": [-2, -1, 1, 3, 4, 3, 1, -1, -2, -2],
    "Night": [3, 2, 0, -2, -1, 2, 3, 2, 2, 2],
    "Rock": [5, 3, -2, -3, 1, 3, 5, 5, 5, 5],
    "Electronic": [5, 4, 1, 0, -2, 2, 4, 5, 5, 5],
    "Pop": [-1, 2, 4, 5, 3, 0, -1, -1, -1, -1],
    "Jazz": [4, 3, 1, 2, -2, -2, 0, 1, 3, 4],
    "Classical": [5, 4, 3, 2, -1, -1, 0, 2, 3, 4],
    "Hip-Hop": [5, 4, 1, 3, -1, -1, 1, -1, 2, 3],
    "R&B": [3, 7, 6, 1, -2, -1, 2, 2, 3, 3],
    "Acoustic": [5, 4, 3, 1, 2, 2, 3, 4, 3, 2],
    "Dance": [6, 5, 2, 0, 0, -3, -5, -5, 0, 0],
    "Metal": [4, 3, 0, -1, -3, 0, 3, 5, 4, 3],
    "Latin": [4, 2, 0, 0, -2, -2, -2, 0, 4, 6],
    "Piano": [3, 2, 0, 3, 4, 2, 4, 5, 3, 4],
    "Lounge": [-3, -1, 2, 4, 2, -2, -1, 1, 2, 1],
    "Deep Bass": [6, 5, 3, 1, 0, -2, -4, -5, -6, -7],
    "Loudness": [6, 4, 0, 0, -2, 0, -1, -5, 5, 1],
    "Small Speakers": [5, 4, 3, 2, 1, 0, -1, -2, -3, -3],
    "Spoken Word": [-4, -1, 0, 1, 3, 5, 5, 4, 2, 0],
}
QUICK_PRESETS = ("Flat", "Bass Boost", "Vocal", "Pop", "Rock", "Electronic", "Night")
BASS_W = (1.0, 0.9, 0.6, 0.25, 0, 0, 0, 0, 0, 0)
TREBLE_W = (0, 0, 0, 0, 0, 0.25, 0.6, 0.9, 1.0, 1.0)


def freq_label(hz):
    return f"{hz} Hz" if hz < 1000 else f"{hz // 1000} kHz"


def fmt_db(v):
    return "0" if v == 0 else "%+d" % v


class EqualizerDialog(GlassDialog):
    """on_change(scope, eq_dict) is called live; scope is 'global' or 'song'.
    on_reset_song() is called when the user drops the song's own equalizer."""

    def __init__(self, parent, engine, global_eq, song_path="", song_title="", song_eq=None,
                 on_change=None, on_reset_song=None, start_scope="global", custom_presets=None, on_presets=None):
        super().__init__(parent)
        self.custom = dict(custom_presets or {})
        self.on_presets = on_presets or (lambda presets: None)
        self._bass = 0
        self._treble = 0
        self.on_change = on_change or (lambda *a: None)
        self.on_reset_song = on_reset_song or (lambda: None)
        self.global_eq = copy.deepcopy(global_eq)
        self.song_path = song_path
        self.song_title = song_title
        self.song_eq = copy.deepcopy(song_eq) if song_eq else None
        self.scope = "song" if (song_path and start_scope == "song") else "global"
        self.eq = copy.deepcopy(self.song_eq or self.global_eq) if self.scope == "song" else copy.deepcopy(self.global_eq)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + 30, SHADOW + 24, SHADOW + 30, SHADOW + 22)
        outer.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.ico = QLabel()
        self.ico.setPixmap(qicon("eq", T.c1.lighter(115) if T.dark else T.c1.darker(115), 24).pixmap(24, 24))
        head.addWidget(self.ico)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Equalizer")
        t.setObjectName("dlgTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("dlgSub")
        titles.addWidget(t)
        titles.addWidget(self.subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        en = QLabel("Enabled")
        en.setObjectName("dlgText")
        head.addWidget(en)
        self.toggle = ToggleSwitch()
        self.toggle.setChecked(bool(self.eq["enabled"]))
        self.toggle.toggled.connect(self._toggled)
        head.addWidget(self.toggle)
        head.addSpacing(8)
        close = GButton("", "x", "flat", 16)
        close.clicked.connect(self.accept)
        head.addWidget(close)
        outer.addLayout(head)

        # scope switch
        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        self.scope_global = GButton("All songs", "library", "chip", 14)
        self.scope_global.clicked.connect(lambda: self._set_scope("global"))
        scope_row.addWidget(self.scope_global)
        self.scope_song = None
        if song_path:
            short = song_title if len(song_title) <= 34 else song_title[:33] + "…"
            self.scope_song = GButton("This song: " + short, "music", "chip", 14)
            self.scope_song.clicked.connect(lambda: self._set_scope("song"))
            scope_row.addWidget(self.scope_song)
        scope_row.addStretch(1)
        self.reset_song_btn = GButton("Use all-songs EQ", "reset", "ghost", 15)
        self.reset_song_btn.clicked.connect(self._reset_song)
        scope_row.addWidget(self.reset_song_btn)
        outer.addLayout(scope_row)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        for name in QUICK_PRESETS:
            b = GButton(name, None, "chip")
            b.clicked.connect(lambda _=False, n=name: self._load_preset(n))
            chips.addWidget(b)
            self.chips[name] = b
        self.more_btn = GButton("All presets", "list-music", "chip", 14)
        self.more_btn.clicked.connect(self._presets_menu)
        chips.addWidget(self.more_btn)
        chips.addStretch(1)
        save = GButton("Save preset", "plus", "ghost", 15)
        save.clicked.connect(self._save_preset)
        chips.addWidget(save)
        reset = GButton("Reset", "reset", "ghost", 15)
        reset.clicked.connect(lambda: self._load_preset("Flat", reset_preamp=True))
        chips.addWidget(reset)
        outer.addLayout(chips)

        tone = QHBoxLayout()
        tone.setSpacing(10)
        bl = QLabel("Bass")
        bl.setObjectName("dlgText")
        self.bass_slider = GlassSlider(Qt.Orientation.Horizontal, -10, 10, bipolar=True)
        self.bass_slider.setFixedWidth(170)
        self.bass_slider.valueChanged.connect(lambda v: self._tone_user("bass", v))
        tl = QLabel("Treble")
        tl.setObjectName("dlgText")
        self.treble_slider = GlassSlider(Qt.Orientation.Horizontal, -10, 10, bipolar=True)
        self.treble_slider.setFixedWidth(170)
        self.treble_slider.valueChanged.connect(lambda v: self._tone_user("treble", v))
        tone.addWidget(bl)
        tone.addWidget(self.bass_slider)
        tone.addSpacing(14)
        tone.addWidget(tl)
        tone.addWidget(self.treble_slider)
        tone.addStretch(1)
        hl = QLabel("Smart headroom")
        hl.setObjectName("dlgText")
        hl.setToolTip("Lowers the level a little when you boost bands, so loud songs do not distort.")
        self.safe_toggle = ToggleSwitch()
        self.safe_toggle.toggled.connect(self._safe_toggled)
        self.headroom = QLabel("")
        self.headroom.setObjectName("dlgFreq")
        tone.addWidget(self.headroom)
        tone.addSpacing(8)
        tone.addWidget(hl)
        tone.addWidget(self.safe_toggle)
        outer.addLayout(tone)

        col_w = EqCurve.COL_W
        curve_row = QHBoxLayout()
        curve_row.addStretch(1)
        curve_row.addSpacing(col_w + 24)
        self.curve = EqCurve(engine, self.eq["values"])
        self.curve.bandChanged.connect(self._curve_user)
        curve_row.addWidget(self.curve)
        curve_row.addStretch(1)
        outer.addLayout(curve_row)

        cols = QHBoxLayout()
        cols.setSpacing(0)
        cols.addStretch(1)
        self.pre_val, self.pre_slider = self._column(cols, "PRE", col_w)
        self.pre_slider.valueChanged.connect(self._preamp_user)
        sep = QFrame()
        sep.setFixedSize(24, 1)
        cols.addWidget(sep)
        self.sliders, self.vals = [], []
        for i, hz in enumerate(EQ_FREQS):
            val, sl = self._column(cols, freq_label(hz), col_w)
            sl.valueChanged.connect(lambda v, ix=i: self._band_user(ix, v))
            self.sliders.append(sl)
            self.vals.append(val)
        cols.addStretch(1)
        outer.addLayout(cols, 1)

        foot = QHBoxLayout()
        hint = QLabel("Drag the curve or sliders · double-click a slider to reset it · presets can be saved as your own")
        hint.setObjectName("dlgFreq")
        foot.addWidget(hint)
        foot.addStretch(1)
        done = GButton("Done", "check", "primary", 16)
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        outer.addLayout(foot)

        self._refresh_all()
        self.setFixedWidth(960)

    def _column(self, layout, label, width):
        col = QVBoxLayout()
        col.setSpacing(6)
        col.setContentsMargins(0, 0, 0, 0)
        val = QLabel("0")
        val.setObjectName("dlgVal")
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl = GlassSlider(Qt.Orientation.Vertical, -20, 20, bipolar=True)
        sl.setMinimumHeight(150)
        fr = QLabel(label)
        fr.setObjectName("dlgFreq")
        fr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(val)
        col.addWidget(sl, 1, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(fr)
        host = QWidget()
        host.setFixedWidth(width)
        host.setLayout(col)
        layout.addWidget(host)
        return val, sl

    # -- state -----------------------------------------------------------------------
    def _emit(self):
        if self.scope == "song":
            self.song_eq = copy.deepcopy(self.eq)
        else:
            self.global_eq = copy.deepcopy(self.eq)
        self.on_change(self.scope, copy.deepcopy(self.eq))
        self._refresh_scope_widgets()

    def _refresh_scope_widgets(self):
        self.scope_global.set_active(self.scope == "global")
        if self.scope_song is not None:
            self.scope_song.set_active(self.scope == "song")
        self.reset_song_btn.setVisible(self.scope == "song" and self.song_eq is not None)
        if self.scope == "song":
            note = "has its own equalizer" if self.song_eq is not None else "uses the all-songs equalizer until you change something"
            self.subtitle.setText(f"“{self.song_title}” {note}")
        else:
            self.subtitle.setText("10-band studio equalizer · applies to every song without its own setting")

    def _refresh_all(self):
        vals = self.eq["values"]
        for i, v in enumerate(vals):
            self.sliders[i].setValue(v)
            self.vals[i].setText(fmt_db(v))
        self.pre_slider.setValue(self.eq["preamp"])
        self.pre_val.setText(fmt_db(self.eq["preamp"]))
        self.curve.set_values(vals)
        enabled = bool(self.eq["enabled"])
        self.curve.enabled = enabled
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)
        for name, chip in self.chips.items():
            chip.set_active(name == self.eq["preset"])
        self.more_btn.set_active(self.eq["preset"] not in self.chips and self.eq["preset"] not in ("Custom", ""))
        self.more_btn.setText(self.eq["preset"] if self.more_btn._active else "All presets")
        self.safe_toggle.blockSignals(True)
        self.safe_toggle.setChecked(bool(self.eq.get("safe", True)))
        self.safe_toggle.blockSignals(False)
        self._update_headroom()
        self._reset_tone()
        for sl in self.sliders + [self.pre_slider, self.bass_slider, self.treble_slider]:
            sl.setEnabled(enabled)
        self._refresh_scope_widgets()
        self.update()

    def _set_scope(self, scope):
        if scope == self.scope or (scope == "song" and not self.song_path):
            return
        self.scope = scope
        if scope == "song":
            self.eq = copy.deepcopy(self.song_eq or self.global_eq)
        else:
            self.eq = copy.deepcopy(self.global_eq)
        self._refresh_all()

    def _reset_song(self):
        self.song_eq = None
        self.on_reset_song()
        self.eq = copy.deepcopy(self.global_eq)
        self._refresh_all()

    def _update_headroom(self):
        from library import effective_preamp
        eff = effective_preamp(self.eq) - float(self.eq["preamp"])
        self.headroom.setText("headroom %+.1f dB" % eff if self.eq.get("safe", True) and eff else "")

    def _reset_tone(self):
        self._bass = self._treble = 0
        for sl in (self.bass_slider, self.treble_slider):
            sl.blockSignals(True)
            sl.setValue(0)
            sl.blockSignals(False)

    def _tone_user(self, which, v):
        old = self._bass if which == "bass" else self._treble
        d = v - old
        if which == "bass":
            self._bass = v
        else:
            self._treble = v
        w = BASS_W if which == "bass" else TREBLE_W
        vals = self.eq["values"]
        for i in range(len(vals)):
            vals[i] = max(-20, min(20, int(round(vals[i] + d * w[i]))))
        for i, x in enumerate(vals):
            self.sliders[i].blockSignals(True)
            self.sliders[i].setValue(x)
            self.sliders[i].blockSignals(False)
            self.vals[i].setText(fmt_db(x))
        self.curve.set_values(vals)
        self._mark_custom()
        self._update_headroom()
        self._emit()

    def _safe_toggled(self, on):
        self.eq["safe"] = bool(on)
        self._update_headroom()
        self._emit()

    def _presets_menu(self):
        menu = style_menu(QMenu(self))
        names = list(EQ_PRESETS)
        acts = {}
        for n in names:
            a = menu.addAction(("●  " if n == self.eq["preset"] else "     ") + n)
            acts[a] = ("load", n)
        if self.custom:
            menu.addSeparator()
            for n in self.custom:
                a = menu.addAction(("●  " if n == self.eq["preset"] else "     ") + n + "   (mine)")
                acts[a] = ("load", n)
            menu.addSeparator()
            sub = style_menu(menu.addMenu("Delete my preset"))
            for n in self.custom:
                acts[sub.addAction(n)] = ("delete", n)
        chosen = menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
        if chosen in acts:
            kind, n = acts[chosen]
            if kind == "load":
                self._load_preset(n)
            else:
                self.custom.pop(n, None)
                self.on_presets(dict(self.custom))
                if self.eq["preset"] == n:
                    self.eq["preset"] = "Custom"
                self._refresh_all()

    def _save_preset(self):
        name, ok = ask_text(self, "Save preset", "Name this equalizer setting so you can use it again.",
                            placeholder="e.g. My car", ok_text="Save", icon="list-plus")
        name = (name or "").strip()[:40]
        if not ok or not name:
            return
        if name in EQ_PRESETS:
            notice(self, "Name already used", "That is the name of a built-in preset. Please choose another one.", "info")
            return
        self.custom[name] = {"values": list(self.eq["values"]), "preamp": int(self.eq["preamp"])}
        self.on_presets(dict(self.custom))
        self.eq["preset"] = name
        self._refresh_all()
        self._emit()

    def _mark_custom(self):
        if self.eq["preset"] != "Custom":
            self.eq["preset"] = "Custom"
            for chip in self.chips.values():
                chip.set_active(False)

    def _band_user(self, i, v):
        self.eq["values"][i] = v
        self.vals[i].setText(fmt_db(v))
        self.curve.set_values(self.eq["values"])
        self._mark_custom()
        self._update_headroom()
        self._emit()

    def _curve_user(self, i, v):
        self.eq["values"][i] = v
        self.sliders[i].setValue(v)
        self.vals[i].setText(fmt_db(v))
        self._mark_custom()
        self._update_headroom()
        self._emit()

    def _preamp_user(self, v):
        self.eq["preamp"] = v
        self.pre_val.setText(fmt_db(v))
        self._update_headroom()
        self._emit()

    def _load_preset(self, name, reset_preamp=False):
        if name in self.custom:
            self.eq["values"] = list(self.custom[name]["values"])
            self.eq["preamp"] = int(self.custom[name].get("preamp", 0))
        elif name in EQ_PRESETS:
            self.eq["values"] = list(EQ_PRESETS[name])
        else:
            return
        self.eq["preset"] = name
        if reset_preamp:
            self.eq["preamp"] = 0
        self._refresh_all()
        self._emit()

    def _toggled(self, on):
        self.eq["enabled"] = bool(on)
        self._refresh_all()
        self._emit()
