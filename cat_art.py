"""Pure-Python SVG generators for the animated cat logo and the cat-ear player buttons.

No Qt in here: every function returns an SVG string for the current animation state, so the
artwork can be checked in any browser.  cat_widgets.py renders it with QSvgRenderer.
"""
import math

ORANGE = "#ff9468"


# -- easing helpers -----------------------------------------------------------------------------------------
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def lerp(a, b, t):
    return a + (b - a) * t


def kf(points, pct):
    """Piece-wise keyframes [(percent, value), ...] with eased segments (CSS `ease`-like)."""
    if pct <= points[0][0]:
        return points[0][1]
    for (p0, v0), (p1, v1) in zip(points, points[1:]):
        if pct <= p1:
            span = (p1 - p0) or 1.0
            return lerp(v0, v1, smooth((pct - p0) / span))
    return points[-1][1]


def bezier(x1, y1, x2, y2, u):
    """CSS cubic-bezier(x1,y1,x2,y2) evaluated at time fraction u."""
    u = clamp(u)
    lo, hi = 0.0, 1.0
    t = u
    for _ in range(24):
        x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
        if x < u:
            lo = t
        else:
            hi = t
        t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3


def tf(tx=0.0, ty=0.0, rot=0.0, sx=1.0, sy=1.0, ox=0.0, oy=0.0):
    """transform string: translate, then rotate/scale about the origin point (ox, oy)."""
    return (f"translate({tx + ox:.3f} {ty + oy:.3f}) rotate({rot:.3f}) "
            f"scale({sx:.4f} {sy:.4f}) translate({-ox:.3f} {-oy:.3f})")


def hexcol(c):
    """'#rrggbb' from a QColor-like (.red/.green/.blue) or a string."""
    if isinstance(c, str):
        return c
    return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())


# ======================================================================================================
# Logo
# ======================================================================================================
NOTE = ('<ellipse rx="11" ry="8" transform="rotate(-20)"/><rect x="8" y="-38" width="4" height="38"/>'
        '<path d="M12 -38q18 4 14 24q-2 -12 -14 -14z"/>')
HEART = "M0 -6C-10 -20 -30 -4 0 18C30 -4 10 -20 0 -6Z"


def _cycle(t, period, delay=0.0):
    """Loop phase 0..1 of an infinite CSS animation with a start delay (None while still waiting)."""
    if t < delay:
        return None
    return ((t - delay) % period) / period


def logo_svg(t, look=(0.0, 0.0), sleep=0.0, blink=None, tap=None, reduced=False):
    """Frame of the animated cat logo.

    t      seconds since start (drives the loops)
    look   (cx, cy) pointer direction, each -1..1
    sleep  0 awake .. 1 asleep (eased by the caller)
    blink  None or progress 0..1 of the current blink
    tap    None or seconds since the logo was tapped (happy squish + hearts, lasts ~1.1 s)
    """
    cx, cy = look
    asleep = sleep > 0.5
    happy = tap is not None and tap < 1.1
    # whole-cat motion -------------------------------------------------------------------------------
    cat_tf = ""
    if happy:
        u = clamp(tap / 0.75)
        sx = kf([(0, 1), (18, 1.09), (42, .95), (68, 1.03), (100, 1)], u * 100)
        sy = kf([(0, 1), (18, .88), (42, 1.08), (68, .97), (100, 1)], u * 100)
        ty = kf([(0, 0), (18, 0), (42, -16), (68, 0), (100, 0)], u * 100)
        cat_tf = tf(0, ty, 0, sx, sy, 256, 330)
    elif asleep:
        ph = (t % 3.2) / 3.2
        k = smooth(1 - abs(ph * 2 - 1))
        s = 1 + 0.025 * k
        cat_tf = tf(0, 3 * k, 0, s, s, 256, 330)
    elif not reduced:
        ph = (t % 0.8) / 0.8
        k = smooth(1 - abs(ph * 2 - 1))
        cat_tf = tf(0, 7 * k, 0, 1, 1, 256, 330)
    # ears --------------------------------------------------------------------------------------------
    eL = eR = 0.0
    if happy and tap < 0.6:
        p = tap / 0.6 * 100
        eL = kf([(0, 0), (25, -16), (50, 6), (75, -8), (100, 0)], p)
        eR = kf([(0, 0), (25, 16), (50, -6), (75, 8), (100, 0)], p)
    elif not asleep and not happy and not reduced:
        a = _cycle(t, 3.4)
        b = _cycle(t, 3.4, 0.5)
        if a is not None:
            eL = kf([(0, 0), (78, 0), (84, -12), (90, 3), (100, 0)], a * 100)
        if b is not None:
            eR = -kf([(0, 0), (78, 0), (84, -12), (90, 3), (100, 0)], b * 100)
    # whiskers, dots, waves, notes --------------------------------------------------------------------
    wk1 = wk2 = 0.0
    dots = 1.0
    w1 = w2 = 0.15
    notes = []
    if not asleep and not reduced:
        a = _cycle(t, 4.0)
        b = _cycle(t, 4.0, 0.3)
        pts = [(0, 0), (70, 0), (78, -4), (86, 3), (100, 0)]
        if a is not None:
            wk1 = kf(pts, a * 100)
        if b is not None:
            wk2 = kf(pts, b * 100)
        ph = (t % 0.8) / 0.8
        dots = 1 + 0.3 * smooth(1 - abs(ph * 2 - 1))
        w1 = lerp(.15, .9, smooth(1 - abs(ph * 2 - 1)))
        if t >= 0.2:
            ph2 = ((t - 0.2) % 0.8) / 0.8
            w2 = lerp(.15, .9, smooth(1 - abs(ph2 * 2 - 1)))
        else:
            w2 = 1.0
        for delay in (0.0, 1.0, 2.0):
            c = _cycle(t, 3.0, delay)
            if c is None:
                notes.append((0.0, 1.0, 1.0))
                continue
            e = ease_out(c)
            ty = lerp(30, -40, e)
            sc = lerp(.6, 1.0, e)
            op = ease_out(c / .2) if c < .2 else 1 - ease_out((c - .2) / .8)
            notes.append((ty, sc, op))
    else:
        notes = [(0, 1, 0)] * 3
    # eyes --------------------------------------------------------------------------------------------
    eye_open = 1.0 - max(sleep, 1.0 if happy else 0.0)
    sy = 1.0 if blink is None else kf([(0, 1), (45, .06), (100, 1)], blink * 100)
    shut_op = sleep if not happy else 0.0
    joy_op = 1.0 if happy else 0.0
    if happy:
        shut_op = 0.0
    brow_ty = 8 * sleep if not happy else -6
    # pupils: kept inside the eye (no clip needed)
    px, py = cx * 7, cy * 8
    nx, ny = px / 6.0, py / 9.0
    r = math.hypot(nx, ny)
    if r > 1:
        px, py = px / r, py / r
    st = sleep

    def eye(x):
        return (f'<g opacity="{eye_open:.3f}" transform="{tf(0, 0, 0, 1, sy, x, 298)}">'
                f'<ellipse cx="{x}" cy="298" rx="29" ry="32" fill="#fff4ea" stroke="#0f1318" stroke-width="5"/>'
                f'<g transform="translate({px:.2f} {py:.2f})"><circle cx="{x}" cy="300" r="23" fill="#8fd14f"/>'
                f'<circle cx="{x}" cy="300" r="22" fill="none" stroke="#4e8f2a" stroke-width="3"/>'
                f'<circle cx="{x}" cy="300" r="13" fill="#0f1318"/><circle cx="{x - 8}" cy="293" r="5.5" fill="#fff"/>'
                f'<circle cx="{x + 9}" cy="309" r="2.5" fill="#fff" opacity=".8"/></g>'
                f'<path d="M{x - 21} 277A29 32 0 0 1 {x + 21} 277Z" fill="#ff9468" stroke="#0f1318" '
                f'stroke-width="5" stroke-linejoin="round"/></g>')

    head_tf = f"translate({cx * 6:.2f} {cy * 5 + st * 8:.2f}) rotate({cx * 5 + st * 6:.2f} 256 330)"
    face_tf = f"translate({cx * 10:.2f} {cy * 7:.2f})"
    pawn = lambda x, y, k: ""  # noqa: E731  (placeholder so the f-strings below stay readable)

    # floating notes
    note_x = [(70, 130, 1.0, "#ff9468"), (448, 118, 1.15, "#ff9468"), (425, 62, .8, "#ffb596")]
    notes_svg = ""
    for (x, y, s0, col), (ty, sc, op) in zip(note_x, notes):
        notes_svg += (f'<g opacity="{op:.3f}" transform="translate(0 {ty:.2f}) {tf(0, 0, 0, sc, sc, x, y)}">'
                      f'<g fill="{col}" transform="translate({x} {y}) scale({s0})">{NOTE}</g></g>')
    # zzz
    zs = ""
    if asleep:
        for i, (zx, zy) in enumerate(((392, 150), (410, 120), (430, 92))):
            c = _cycle(t, 3.0, float(i))
            if c is None:
                continue
            tx = 22 * ease_out(c)
            ty = lerp(22, -44, ease_out(c))
            sc = lerp(.5, 1.15, ease_out(c))
            op = .95 * ease_out(c / .25) if c < .25 else .95 * (1 - ease_out((c - .25) / .75))
            zs += (f'<text x="{zx}" y="{zy}" opacity="{op:.3f}" fill="#ff9468" font-size="34" font-weight="bold" '
                   f'font-family="Segoe UI, Arial, sans-serif" transform="translate({tx:.2f} {ty:.2f}) '
                   f'{tf(0, 0, 0, sc, sc, zx + 9, zy - 12)}">z</text>')
    # hearts
    hearts = ""
    if happy:
        for (hx, hy), delay in (((180, 120), 0.0), ((256, 92), 0.12), ((332, 120), 0.24)):
            c = (tap - delay) / 1.1
            if c <= 0 or c >= 1:
                continue
            e = ease_out(c)
            ty = lerp(12, -58, e)
            sc = lerp(.3, 1.1, e)
            op = ease_out(c / .25) if c < .25 else 1 - ease_out((c - .25) / .75)
            hearts += (f'<g transform="translate({hx} {hy})"><path d="{HEART}" fill="#ff6f8a" opacity="{op:.3f}" '
                       f'transform="translate(0 {ty:.2f}) {tf(0, 0, 0, sc, sc, 0, 4)}"/></g>')

    wave = lambda d, op: f'<path d="{d}" opacity="{op:.3f}"/>'  # noqa: E731
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
{notes_svg}{zs}
<g transform="{cat_tf}">
<g fill="none" stroke="#ff9468" stroke-width="7" stroke-linecap="round">
{wave("M56 276q-14 33 0 66", w1)}{wave("M36 258q-26 51 0 102", w2)}
{wave("M456 276q14 33 0 66", w1)}{wave("M476 258q26 51 0 102", w2)}</g>
<g transform="{head_tf}">
<g transform="{tf(0, 0, eL, 1, 1, 174, 250)}"><path d="M132 250L126 112L222 184Z" fill="#ff9468" stroke="#ff9468" stroke-width="14" stroke-linejoin="round"/><path d="M150 214L148 148L196 184Z" fill="#ffb596"/><path d="M152 214l10 -10l4 10l8 -8l4 10z" fill="#ffe3cf"/></g>
<g transform="{tf(0, 0, eR, 1, 1, 338, 250)}"><path d="M380 250L386 112L290 184Z" fill="#ff9468" stroke="#ff9468" stroke-width="14" stroke-linejoin="round"/><path d="M362 214L364 148L316 184Z" fill="#ffb596"/><path d="M360 214l-10 -10l-4 10l-8 -8l-4 10z" fill="#ffe3cf"/></g>
<g fill="#ff9468" stroke="#ff9468" stroke-width="8" stroke-linejoin="round"><path d="M172 370L146 382L178 390Z"/><path d="M184 392L162 412L196 408Z"/><path d="M340 370L366 382L334 390Z"/><path d="M328 392L350 412L316 408Z"/></g>
<ellipse cx="256" cy="292" rx="144" ry="118" fill="#ff9468"/>
<g transform="{face_tf}">
<g stroke="#c9582c" stroke-width="9" stroke-linecap="round" fill="none"><path d="M256 188v38"/><path d="M228 196q8 14 5 30"/><path d="M284 196q-8 14 -5 30"/></g>
<ellipse cx="238" cy="348" rx="27" ry="21" fill="#ffe3cf"/><ellipse cx="274" cy="348" rx="27" ry="21" fill="#ffe3cf"/>
<g fill="#d98a63"><circle cx="224" cy="342" r="2.2"/><circle cx="233" cy="348" r="2.2"/><circle cx="222" cy="353" r="2.2"/><circle cx="288" cy="342" r="2.2"/><circle cx="279" cy="348" r="2.2"/><circle cx="290" cy="353" r="2.2"/></g>
<g transform="rotate(28 172 352)"><rect x="152" y="344" width="40" height="15" rx="4" fill="#f3d6b0" stroke="#c9a47a" stroke-width="2"/><rect x="164" y="344" width="16" height="15" fill="#e6bd8b"/></g>
<g transform="translate(0 {brow_ty:.2f})" fill="none" stroke="#8a3d1f" stroke-width="6.5" stroke-linecap="round"><path d="M180 254Q204 244 230 252"/><path d="M282 252Q308 244 332 254"/></g>
{eye(206)}
<path d="M180 300q26 20 52 0" opacity="{shut_op:.3f}" fill="none" stroke="#0f1318" stroke-width="10" stroke-linecap="round"/>
<path d="M180 306q26 -26 52 0" opacity="{joy_op:.3f}" fill="none" stroke="#0f1318" stroke-width="10" stroke-linecap="round"/>
{eye(306)}
<path d="M280 300q26 20 52 0" opacity="{shut_op:.3f}" fill="none" stroke="#0f1318" stroke-width="10" stroke-linecap="round"/>
<path d="M280 306q26 -26 52 0" opacity="{joy_op:.3f}" fill="none" stroke="#0f1318" stroke-width="10" stroke-linecap="round"/>
<path d="M243 334q13 -7 26 0q-2 11 -13 15q-11 -4 -13 -15z" fill="#0f1318"/><ellipse cx="250" cy="337" rx="4" ry="1.8" fill="#fff" opacity=".5"/>
<path d="M256 349v6M256 355q-12 13 -27 4M256 355q12 13 27 4" fill="none" stroke="#0f1318" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
<g transform="{tf(0, 0, wk1, 1, 1, 177, 349)}" fill="none" stroke="#7a3f26" stroke-width="3.5" stroke-linecap="round" opacity=".7"><path d="M204 338l-48 -10M202 348l-52 2M204 358l-46 12"/></g>
<g transform="{tf(0, 0, wk2, 1, 1, 335, 349)}" fill="none" stroke="#7a3f26" stroke-width="3.5" stroke-linecap="round" opacity=".7"><path d="M308 338l48 -10M310 348l52 2M308 358l46 12"/></g>
</g>
<path d="M114 300C104 118 408 118 398 300" fill="none" stroke="#1a1f26" stroke-width="20" stroke-linecap="round"/>
<path d="M114 300C104 118 408 118 398 300" fill="none" stroke="#ff9468" stroke-width="3" stroke-linecap="round" opacity=".55" transform="translate(0 -1)"/>
<rect x="78" y="256" width="62" height="106" rx="28" fill="#1a1f26" stroke="#ff9468" stroke-width="6"/>
<rect x="372" y="256" width="62" height="106" rx="28" fill="#1a1f26" stroke="#ff9468" stroke-width="6"/>
<circle cx="109" cy="309" r="11" fill="#ff9468" transform="{tf(0, 0, 0, dots, dots, 109, 309)}"/><circle cx="403" cy="309" r="11" fill="#ff9468" transform="{tf(0, 0, 0, dots, dots, 403, 309)}"/>
</g></g>{hearts}</svg>'''


# ======================================================================================================
# Player buttons (cat ears)
# ======================================================================================================
ICONS = {
    "shuffle": '<path d="M16 3h5v5l-1.8-1.8-4.4 4.4-1.4-1.4 4.4-4.4zM3 6h4.5l9.6 12H21v2h-5.9L6.5 8H3zM3 18h3.5l2-2.5 1.4 1.7L7.5 20H3zm13.6-4.6 1.4-1.4 3 3V21h-5l1.8-1.8z"/>',
    "prev": '<rect x="5" y="6" width="2.4" height="12" rx="1"/><path d="M19 6.5v11L9.5 12z"/>',
    "next": '<rect x="16.6" y="6" width="2.4" height="12" rx="1"/><path d="M5 6.5v11L14.5 12z"/>',
    "play": '<path d="M8 5v14l11-7z"/>',
    "pause": '<path d="M7 5h3.5v14H7zm6.5 0H17v14h-3.5z"/>',
    "repeat": '<path d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z"/>',
}
PAW = ('<ellipse cx="12" cy="16" rx="6" ry="5"/><circle cx="5" cy="9" r="2.4"/><circle cx="9.5" cy="4.5" r="2.4"/>'
       '<circle cx="14.5" cy="4.5" r="2.4"/><circle cx="19" cy="9" r="2.4"/>')
WHISK = "M3 6l9 4M2 12h10M3 18l9-4M91 6l-9 4M92 12H82M91 18l-9-4"

SMALL = (42, 65)       # toggle / prev / next widget size (px); button circle centre at (21, 30)
PLAY = (94, 90)        # play button widget size; circle centre at (47, 45)


def palette(dark, accent):
    if dark:
        return {"ac": accent, "btn": "#1a1f26", "dim": "#8a929c", "ink": "#0f1318", "ic": "#cfd5dc"}
    return {"ac": accent, "btn": "#e7dfd6", "dim": "#6b625a", "ink": "#ffffff", "ic": "#4a423b"}


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(lerp(x, y, t))) for x, y in zip(a, b))


def _ear(x, y, w, h, side, rot, color):
    """Triangle ear (CSS clip-path polygon) rotated about its bottom centre."""
    pts = [(0, h), (0.22 * w if side == "l" else 0.78 * w, 0), (w, h)]
    d = " ".join(f"{x + px:.2f},{y + py:.2f}" for px, py in pts)
    return f'<polygon points="{d}" fill="{color}" transform="{tf(0, 0, rot, 1, 1, x + w / 2, y + h)}"/>'


def button_svg(kind, dark, accent, icon=None, hover=0.0, on=False, paw=0.0, press=1.0,
               tap=None, pop=None, glow=None, badge=""):
    """kind: toggle | prev | next | play.

    hover 0..1, on (toggle active), paw 0..1.2 (scale, springs), press 1.0..0.88 (scale),
    tap seconds since click (None when idle), pop 0..1 (play icon swap), glow 0..1 (playing pulse),
    badge: small text (repeat "1").
    """
    pal = palette(dark, hexcol(accent))
    ac = pal["ac"]
    if kind == "play":
        W, H = PLAY
        ccx, ccy, rad = 47.0, 45.0, 33.0
    else:
        W, H = SMALL
        ccx, ccy, rad = 21.0, 30.0, 21.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">']
    # glow ring (playing) - drawn behind everything and NOT scaled with the press
    if kind == "play" and glow is not None:
        k = smooth(1 - abs(glow * 2 - 1))
        spread = 9 * k
        out.append(f'<circle cx="{ccx}" cy="{ccy}" r="{rad + spread:.2f}" fill="{ac}" opacity="{0.25 * (1 - k):.3f}"/>')
    out.append(f'<g transform="{tf(0, 0, 0, press, press, ccx, ccy)}">')

    u = tap if tap is not None else 99.0
    # body ---------------------------------------------------------------------------------------------
    if kind == "play":
        ear_l = ear_r = 0.0
        if u < .45:
            p = u / .45 * 100
            ear_l = kf([(0, 0), (40, -16), (70, 5), (100, 0)], p)
            ear_r = kf([(0, 0), (40, 16), (70, -5), (100, 0)], p)
        x0, y0 = ccx - rad, ccy - rad
        out.append(_ear(x0 + 7, y0 - 9, 22, 22, "l", ear_l, ac))
        out.append(_ear(x0 + rad * 2 - 7 - 22, y0 - 9, 22, 22, "r", ear_r, ac))
        out.append(f'<circle cx="{ccx}" cy="{ccy}" r="{rad}" fill="{ac}"/>')
        wsx, wrot = 1.0, 0.0
        if u < .45:
            p = u / .45 * 100
            wsx = kf([(0, 1), (40, 1.08), (70, .98), (100, 1)], p)
            wrot = kf([(0, 0), (40, -3), (70, 2), (100, 0)], p)
        out.append(f'<g transform="translate({ccx - 47} {ccy - 12}) {tf(0, 0, wrot, wsx, 1, 47, 12)}" fill="none" '
                   f'stroke="{ac}" stroke-width="1.6" stroke-linecap="round" opacity=".55"><path d="{WHISK}"/></g>')
        icol = pal["ink"]
        isz = 27.0
    else:
        if kind in ("prev", "next"):
            ear_l = ear_r = 0.0
            if u < .45:
                p = u / .45 * 100
                ear_l = kf([(0, 0), (40, -16), (70, 5), (100, 0)], p)
                ear_r = kf([(0, 0), (40, 16), (70, -5), (100, 0)], p)
            out.append(_ear(3, 30 - 21 - 5, 13, 13, "l", ear_l, pal["btn"]))
            out.append(_ear(42 - 3 - 13, 30 - 21 - 5, 13, 13, "r", ear_r, pal["btn"]))
            out.append(f'<circle cx="{ccx}" cy="{ccy}" r="{rad}" fill="{pal["btn"]}"/>')
            base = pal["ic"]
        else:
            base = ac if on else pal["dim"]
        icol = _mix(base, ac, hover) if (kind != "toggle" or not on) else ac
        isz = 20.0
    # icon -----------------------------------------------------------------------------------------------
    name = icon or kind
    if kind == "toggle" and name not in ICONS:
        name = "shuffle"
    ix, iy, irot, isc, iop = 0.0, 0.0, 0.0, 1.0, 1.0
    if kind == "prev" and u < .35:
        iy_x = kf([(0, 0), (40, -5), (100, 0)], u / .35 * 100)
        ix = iy_x
    if kind == "next" and u < .35:
        ix = kf([(0, 0), (40, 5), (100, 0)], u / .35 * 100)
    if kind == "toggle" and name == "shuffle" and u < .4:
        irot = kf([(0, 0), (25, -14), (60, 12), (100, 0)], u / .4 * 100)
    if kind == "toggle" and name == "repeat" and u < .5:
        irot = 360 * bezier(.4, 0, .2, 1, u / .5)
    if kind == "play" and pop is not None and pop < 1:
        isc = lerp(.4, 1.0, bezier(.3, 1.8, .5, 1, pop))
        iop = clamp(pop / .15)
    s = isz / 24.0
    cxi, cyi = ccx + ix, ccy
    out.append(f'<g opacity="{iop:.3f}" fill="{icol}" transform="translate({cxi:.2f} {cyi:.2f}) rotate({irot:.2f}) '
               f'scale({isc:.4f}) translate({-isz / 2:.2f} {-isz / 2:.2f}) scale({s:.4f})">{ICONS[name]}</g>')
    if badge and kind == "toggle":
        out.append(f'<text x="{ccx + 7:.1f}" y="{ccy + 5:.1f}" font-size="9" font-weight="bold" fill="{icol}" '
                   f'font-family="Segoe UI, Arial, sans-serif" text-anchor="middle">{badge}</text>')
    # paw indicator (toggles) -------------------------------------------------------------------------
    if kind == "toggle" and paw > 0.01:
        px, py = ccx - 5.5, ccy + 21 + 12 - 11
        out.append(f'<g fill="{ac}" transform="translate({px + 5.5:.2f} {py + 5.5:.2f}) scale({paw:.3f}) '
                   f'translate(-5.5 -5.5) scale({11 / 24:.4f})">{PAW}</g>')
    out.append("</g></svg>")
    return "\n".join(out)
