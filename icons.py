"""Vector icon set (24px grid, rounded-stroke style) rendered through QtSvg."""
from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor
from PySide6.QtCore import Qt
from PySide6.QtSvg import QSvgRenderer

S, F = "stroke", "fill"

ICONS = {
    "play": (F, '<polygon points="7,4 20,12 7,20"/>'),
    "pause": (F, '<rect x="6" y="4" width="4.2" height="16" rx="1.4"/><rect x="13.8" y="4" width="4.2" height="16" rx="1.4"/>'),
    "prev": (F, '<polygon points="19,5 9,12 19,19"/><rect x="5" y="5" width="2.6" height="14" rx="1.1"/>'),
    "next": (F, '<polygon points="5,5 15,12 5,19"/><rect x="16.4" y="5" width="2.6" height="14" rx="1.1"/>'),
    "shuffle": (S, '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/>'
                   '<path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>'),
    "repeat": (S, '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'),
    "repeat-1": (S, '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4"/>'),
    "heart": (S, '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>'),
    "heart-fill": (F, '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>'),
    "home": (S, '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>'),
    "library": (S, '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>'),
    "music": (S, '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'),
    "list-music": (S, '<path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/><path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/>'),
    "list-plus": (S, '<path d="M11 12H3"/><path d="M16 6H3"/><path d="M16 18H3"/><path d="M18 9v6"/><path d="M21 12h-6"/>'),
    "plus": (S, '<path d="M5 12h14"/><path d="M12 5v14"/>'),
    "search": (S, '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    "folder-plus": (S, '<path d="M12 10v6"/><path d="M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    "eq": (S, '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/><path d="M2 14h4"/><path d="M10 8h4"/><path d="M18 16h4"/>'),
    "volume-2": (S, '<path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.4 18.4a9 9 0 0 0 0-12.8"/>'),
    "volume-1": (S, '<path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z"/><path d="M16 9a5 5 0 0 1 0 6"/>'),
    "volume-x": (S, '<path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/>'),
    "trash": (S, '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><path d="M10 11v6"/><path d="M14 11v6"/>'),
    "x": (S, '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
    "clock": (S, '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
    "disc": (S, '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="2.5"/>'),
    "pulse": (S, '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>'),
    "reset": (S, '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>'),
    "sparkles": (S, '<path d="M9.9 4.2 11 7.6a2 2 0 0 0 1.4 1.4l3.4 1.1-3.4 1.1a2 2 0 0 0-1.4 1.4l-1.1 3.4-1.1-3.4a2 2 0 0 0-1.4-1.4L4 10.1 7.4 9a2 2 0 0 0 1.4-1.4z"/><path d="M19 3v4"/><path d="M21 5h-4"/><path d="M19 17v4"/><path d="M21 19h-4"/>'),
    "edit": (S, '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
    "check": (S, '<path d="M20 6 9 17l-5-5"/>'),
    "settings": (S, '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.2a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.2a2 2 0 0 1 1 1.7V20a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.2a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.2a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
    "sun": (S, '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'),
    "moon": (S, '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>'),
    "image": (S, '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>'),
    "palette": (S, '<path d="M12 22a1 1 0 0 1 0-20 10 9 0 0 1 10 9 5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z"/><circle cx="13.5" cy="6.5" r=".6"/><circle cx="17.5" cy="10.5" r=".6"/><circle cx="6.5" cy="12.5" r=".6"/><circle cx="8.5" cy="7.5" r=".6"/>'),
    "info": (S, '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    "globe": (S, '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'),
    "download": (S, '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'),
    "cloud": (S, '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>'),
    "link": (S, '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'),
    "chevron-left": (S, '<path d="m15 18-6-6 6-6"/>'),
    "chevron-right": (S, '<path d="m9 18 6-6-6-6"/>'),
    "more": (F, '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>'),
    "grip": (F, '<circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/>'),
    "history": (S, '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>'),
    "skip-song": (S, '<path d="M5 4v16"/><path d="m9 12 10-7v14z"/>'),
    "waves": (S, '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>'),
}

_cache = {}


def svg_source(name, color):
    kind, body = ICONS[name]
    hexc = color.name(QColor.NameFormat.HexRgb)
    a = "%.3f" % color.alphaF()
    if kind == S:
        g = f'fill="none" stroke="{hexc}" stroke-opacity="{a}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    else:
        g = f'fill="{hexc}" fill-opacity="{a}" stroke="{hexc}" stroke-opacity="{a}" stroke-width="1.6" stroke-linejoin="round"'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><g {g}>{body}</g></svg>'


def _renderer(name, color):
    key = (name, color.rgba())
    r = _cache.get(key)
    if r is None:
        r = QSvgRenderer(QByteArray(svg_source(name, color).encode("utf-8")))
        _cache[key] = r
    return r


def draw_icon(painter, name, rect, color):
    """Paint icon `name` into QRectF `rect` using `color` (alpha respected)."""
    _renderer(name, color).render(painter, QRectF(rect))


def qicon(name, color, size=18):
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _renderer(name, color).render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)
