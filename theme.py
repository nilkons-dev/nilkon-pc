"""Theme palette (dark / light), accent presets and small colour helpers."""
import zlib

from PySide6.QtGui import QColor

FONT_FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "SF Pro Display", "Inter", "Helvetica Neue", "Arial"]
FONT_CSS = '"Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def hsv(h, s, v, a=1.0):
    return QColor.fromHsvF(h % 1.0, clamp(s), clamp(v), clamp(a))


def alpha(color, a):
    """Copy of `color` with alpha `a` (0..1)."""
    c = QColor(color)
    c.setAlphaF(clamp(a))
    return c


def white(a):
    """Pure white (used for specular highlights in both modes)."""
    return QColor(255, 255, 255, int(255 * clamp(a)))


def lerp_color(c1, c2, t):
    t = clamp(t)
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def hue_for(text):
    """Stable hue (0..1) derived from a string."""
    return (zlib.crc32(text.encode("utf-8", "ignore")) % 360) / 360.0


def circular_lerp(a, b, t):
    d = ((b - a + 0.5) % 1.0) - 0.5
    return (a + d * t) % 1.0


def smoothstep(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def nice_time(ms):
    sec = max(0, int(ms // 1000))
    return f"{sec // 60}:{sec % 60:02d}"


def text_baseline(fm, rect_top, rect_height):
    """Baseline y that vertically centres text of font metrics `fm` in a box."""
    return rect_top + (rect_height + fm.ascent() - fm.descent()) / 2.0


# name -> (colour 1, colour 2, colour 3).  Colour 1 is the main accent.
ACCENTS = {
    "Cat Orange": ("#FF9468", "#FFB596", "#F59E0B"),
    "Nilkon Blue": ("#3B82F6", "#22D3EE", "#6366F1"),
    "Deep Ocean": ("#2563EB", "#0EA5E9", "#38BDF8"),
    "Midnight Indigo": ("#4F46E5", "#3B82F6", "#8B5CF6"),
    "Aurora": ("#34D399", "#22D3EE", "#818CF8"),
    "Sunset": ("#FB7185", "#F59E0B", "#C084FC"),
    "Neon": ("#F43F5E", "#A855F7", "#22D3EE"),
    "Ice": ("#E0F2FE", "#7DD3FC", "#A5B4FC"),
}
DEFAULT_ACCENT = "Cat Orange"


class Theme:
    """Mutable palette shared by every painted widget.

    c1..c3 are the *current* accent colours; the engine eases them towards t1..t3
    so theme changes cross-fade instead of snapping.
    """

    def __init__(self):
        self.mode = "dark"
        self.name = DEFAULT_ACCENT
        self.adaptive = False
        self.hue = 0.6
        self.t1 = self.c1 = QColor(ACCENTS[DEFAULT_ACCENT][0])
        self.t2 = self.c2 = QColor(ACCENTS[DEFAULT_ACCENT][1])
        self.t3 = self.c3 = QColor(ACCENTS[DEFAULT_ACCENT][2])

    # -- mode ------------------------------------------------------------------------
    @property
    def dark(self):
        return self.mode != "light"

    def set_mode(self, mode):
        self.mode = "light" if mode == "light" else "dark"

    # -- accent ----------------------------------------------------------------------
    def set_accent(self, name, snap=False):
        cols = ACCENTS.get(name) or ACCENTS[DEFAULT_ACCENT]
        self.name = name if name in ACCENTS else DEFAULT_ACCENT
        self.set_targets(QColor(cols[0]), QColor(cols[1]), QColor(cols[2]), snap)

    def set_hue_targets(self, h, snap=False):
        self.hue = h % 1.0
        self.set_targets(hsv(h, 0.62, 1.0), hsv(h + 0.14, 0.60, 1.0), hsv(h + 0.34, 0.60, 1.0), snap)

    def set_targets(self, c1, c2, c3, snap=False):
        self.t1, self.t2, self.t3 = QColor(c1), QColor(c2), QColor(c3)
        if snap:
            self.c1, self.c2, self.c3 = QColor(c1), QColor(c2), QColor(c3)

    def settled(self):
        return all(abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) < 4
                   for a, b in ((self.c1, self.t1), (self.c2, self.t2), (self.c3, self.t3)))

    def step(self, k):
        """Ease current colours towards the targets (k = 0..1 per tick)."""
        self.c1 = lerp_color(self.c1, self.t1, k)
        self.c2 = lerp_color(self.c2, self.t2, k)
        self.c3 = lerp_color(self.c3, self.t3, k)
        if self.settled():
            self.c1, self.c2, self.c3 = QColor(self.t1), QColor(self.t2), QColor(self.t3)

    # -- palette helpers ---------------------------------------------------------------
    @property
    def on_accent(self):
        """Readable text colour on top of the accent gradient."""
        m = lerp_color(self.c1, self.c2, 0.5)
        lum = (0.299 * m.red() + 0.587 * m.green() + 0.114 * m.blue()) / 255.0
        return QColor(8, 14, 34) if lum > 0.64 else QColor(255, 255, 255)


T = Theme()


def ink(a=1.0):
    """Foreground colour: white on dark, deep navy on light."""
    if T.dark:
        return QColor(255, 255, 255, int(255 * clamp(a)))
    return QColor(12, 20, 44, int(255 * clamp(a)))


def surface(a=1.0):
    """Glass underlay colour: near-black navy on dark, white on light."""
    if T.dark:
        return QColor(5, 9, 22, int(255 * clamp(a)))
    return QColor(255, 255, 255, int(255 * clamp(a)))


def build_qss():
    """Application stylesheet for the current mode."""
    d = T.dark
    fg = "#f1f5ff" if d else "#0c142c"
    sub = "rgba(255,255,255,0.58)" if d else "rgba(12,20,44,0.62)"
    eyeb = "rgba(255,255,255,0.46)" if d else "rgba(12,20,44,0.50)"
    hair = "rgba(255,255,255,0.16)" if d else "rgba(12,20,44,0.18)"
    field = "rgba(255,255,255,0.07)" if d else "rgba(255,255,255,0.62)"
    field_f = "rgba(255,255,255,0.11)" if d else "rgba(255,255,255,0.90)"
    a1 = T.t1
    menu_bg = "rgb(21,25,34)" if d else "rgb(255,255,255)"
    menu_edge = "rgba(255,255,255,0.11)" if d else "rgba(12,20,44,0.14)"
    menu_hi = "rgba(255,255,255,0.075)" if d else "rgba(12,20,44,0.07)"
    accent_hex = a1.name()
    dlg = "#0a0f1e" if d else "#eef2fb"
    scroll = "rgba(255,255,255,0.18)" if d else "rgba(12,20,44,0.25)"
    scroll_h = "rgba(255,255,255,0.34)" if d else "rgba(12,20,44,0.42)"
    pill_bg = "rgba(255,255,255,0.08)" if d else "rgba(12,20,44,0.07)"
    pill_fg = "rgba(255,255,255,0.80)" if d else "rgba(12,20,44,0.78)"
    return """
QWidget { background: transparent; color: %(fg)s; font-family: %(font)s; font-size: 13px; }
QMainWindow { background: %(dlg)s; }
QLabel#brand { font-size: 22px; font-weight: 800; color: %(fg)s; }
QLabel#eyebrow { color: %(eyeb)s; font-size: 10px; font-weight: 800; }
QLabel#muted { color: %(sub)s; font-size: 12px; }
QLabel#heroTitle { font-size: 30px; font-weight: 800; color: %(fg)s; }
QLabel#heroDesc { font-size: 13px; color: %(sub)s; }
QLabel#sectionTitle { font-size: 22px; font-weight: 800; }
QLabel#rowTitle { font-size: 17px; font-weight: 800; }
QLabel#nowTitle { font-size: 21px; font-weight: 800; }
QLabel#nowSub { font-size: 13px; color: %(sub)s; }
QLabel#dockTitle { font-size: 15px; font-weight: 700; }
QLabel#time { font-size: 11px; font-weight: 600; color: %(sub)s; }
QLabel#pill { background: %(pill_bg)s; border: 1px solid %(hair)s; border-radius: 10px;
              padding: 2px 10px; font-size: 11px; font-weight: 600; color: %(pill_fg)s; }
QLabel#emptyTitle { font-size: 20px; font-weight: 800; }
QLabel#dlgTitle { font-size: 22px; font-weight: 700; }
QLabel#dlgSub { font-size: 12px; color: %(sub)s; }
QLabel#dlgHead { font-size: 15px; font-weight: 700; }
QLabel#dlgText { font-size: 13px; color: %(sub)s; }
QLabel#dlgVal { font-size: 12px; font-weight: 700; }
QLabel#dlgFreq { font-size: 11px; font-weight: 600; color: %(sub)s; }
QLineEdit#search { background: %(field)s; border: 1px solid %(hair)s; border-radius: 21px;
                   padding: 0px 16px 0px 8px; min-height: 40px; color: %(fg)s;
                   selection-background-color: rgba(59,130,246,0.55); font-size: 13px; }
QLineEdit#search:focus { border: 1px solid rgba(96,165,250,0.85); background: %(field_f)s; }
QListWidget { background: transparent; border: none; outline: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 6px 2px; }
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(scroll_h)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0px; }
QMenu { background-color: %(menu_bg)s; border: 1px solid %(menu_edge)s; border-radius: 12px; padding: 6px; color: %(fg)s; }
QMenu::item { padding: 9px 30px 9px 8px; border-radius: 8px; margin: 1px 0px; }
QMenu::item:selected { background: %(menu_hi)s; }
QMenu::item:disabled { color: %(sub)s; }
QMenu::icon { padding-left: 8px; }
QMenu::right-arrow { width: 14px; }
QMenu::separator { height: 1px; background: %(hair)s; margin: 6px 8px; }
QToolTip { background-color: %(menu_bg)s; color: %(fg)s; border: 1px solid %(menu_edge)s; padding: 6px 10px; }
QLineEdit#dlgInput { background: %(field)s; border: 1px solid %(hair)s; border-radius: 14px; padding: 0px 14px;
                     min-height: 44px; color: %(fg)s; font-size: 14px; selection-background-color: rgba(59,130,246,0.55); }
QLineEdit#dlgInput:focus { border: 1px solid %(accent)s; background: %(field_f)s; }
QLabel#dlgBadge { background: %(menu_hi)s; border: 1px solid %(menu_edge)s; border-radius: 23px; }
QDialog, QMessageBox, QInputDialog { background-color: %(dlg)s; }
QMessageBox QLabel, QInputDialog QLabel { color: %(fg)s; }
QPushButton { background: %(field)s; border: 1px solid %(hair)s; border-radius: 10px;
              padding: 8px 18px; min-width: 72px; color: %(fg)s; }
QPushButton:hover { background: %(field_f)s; }
QPushButton:default { background: rgba(59,130,246,0.55); border-color: rgba(147,197,253,0.8); color: #ffffff; }
QInputDialog QLineEdit, QComboBox { background: %(field)s; border: 1px solid %(hair)s; border-radius: 8px;
                                    padding: 7px 10px; color: %(fg)s; }
""" % {"fg": fg, "sub": sub, "eyeb": eyeb, "hair": hair, "field": field, "field_f": field_f, "menu_bg": menu_bg,
       "menu_hi": menu_hi, "menu_edge": menu_edge, "accent": accent_hex, "dlg": dlg, "scroll": scroll, "scroll_h": scroll_h, "pill_bg": pill_bg,
       "pill_fg": pill_fg, "font": FONT_CSS}
