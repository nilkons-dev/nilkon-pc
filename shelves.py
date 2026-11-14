"""Spotify-style home of the Online page: rows ("shelves") of cover cards that scroll sideways with arrows on both sides."""
from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QPen, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame

from icons import draw_icon
from theme import T, alpha, ink
from tracklist import draw_thumb
from visuals import draw_mini_bars
from widgets import ui_font, round_path, NOPEN, NOBRUSH, AA

COVER = 150
CARD_W = 166
GAP = 6
HEAD_H = 56
TEXT_H = 50
SHELF_H = HEAD_H + COVER + TEXT_H + 22
ARROW = 38


class Shelf(QWidget):
    playRequested = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, host, title, subtitle, items, parent=None):
        super().__init__(parent)
        self.host = host
        self.title, self.subtitle, self.items = title, subtitle, list(items)
        self.offset = 0.0
        self.hover = -1
        self.hover_zone = ""
        self.inside = False
        self.setMouseTracking(True)
        self.setFixedHeight(SHELF_H)
        self.f_title = ui_font(21, QFont.Weight.Bold)
        self.f_small = ui_font(12, QFont.Weight.Normal)
        self.f_name = ui_font(13, QFont.Weight.DemiBold)
        self.f_art = ui_font(12, QFont.Weight.Normal)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(380)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._anim_step)

    # -- geometry ---------------------------------------------------------------------------------
    def max_offset(self):
        return max(0.0, len(self.items) * (CARD_W + GAP) - GAP - (self.width() - 8))

    def card_rect(self, i):
        return QRectF(4 + i * (CARD_W + GAP) - self.offset, HEAD_H, CARD_W, COVER + TEXT_H)

    def cover_rect(self, i):
        r = self.card_rect(i)
        return QRectF(r.left() + 8, r.top() + 4, COVER, COVER)

    def arrow_rect(self, left):
        y = HEAD_H + 4 + COVER / 2 - ARROW / 2
        return QRectF(8 if left else self.width() - ARROW - 8, y, ARROW, ARROW)

    def arrows(self):
        mo = self.max_offset()
        return self.offset > 1, self.offset < mo - 1

    def _hit(self, pos):
        for left in (True, False):
            can = self.arrows()[0 if left else 1]
            if can and self.inside and self.arrow_rect(left).contains(pos):
                return -1, "arrow-left" if left else "arrow-right"
        if pos.y() < HEAD_H:
            return -1, ""
        i = int((pos.x() - 4 + self.offset) // (CARD_W + GAP))
        if 0 <= i < len(self.items) and self.card_rect(i).contains(pos):
            cr = self.cover_rect(i)
            play = QRectF(cr.right() - 52, cr.bottom() - 52, 44, 44)
            more = QRectF(cr.right() - 38, cr.top() + 6, 32, 32)
            if play.contains(pos):
                return i, "play"
            if more.contains(pos):
                return i, "more"
            return i, "card"
        return -1, ""

    # -- scrolling --------------------------------------------------------------------------------
    def _anim_step(self, v):
        self.offset = float(v)
        self.update()

    def scroll_by(self, direction):
        step = (CARD_W + GAP) * max(1, int((self.width() - 8) // (CARD_W + GAP)) - 1)
        target = min(self.max_offset(), max(0.0, self.offset + direction * step))
        self.anim.stop()
        self.anim.setStartValue(self.offset)
        self.anim.setEndValue(target)
        self.anim.start()

    def wheelEvent(self, e):
        dx = e.angleDelta().x()
        if dx or e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            d = dx or e.angleDelta().y()
            self.anim.stop()
            self.offset = min(self.max_offset(), max(0.0, self.offset - d * 0.9))
            self.update()
            e.accept()
        else:
            e.ignore()                                   # a normal wheel scrolls the page

    def resizeEvent(self, e):
        self.offset = min(self.offset, self.max_offset())
        super().resizeEvent(e)

    # -- mouse ------------------------------------------------------------------------------------
    def enterEvent(self, e):
        self.inside = True
        self.update()

    def leaveEvent(self, e):
        self.inside = False
        self.hover, self.hover_zone = -1, ""
        self.unsetCursor()
        self.update()

    def mouseMoveEvent(self, e):
        i, zone = self._hit(e.position())
        if (i, zone) != (self.hover, self.hover_zone):
            self.hover, self.hover_zone = i, zone
            self.setCursor(Qt.CursorShape.PointingHandCursor if zone else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        i, zone = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton:
            if zone == "arrow-left":
                self.scroll_by(-1)
            elif zone == "arrow-right":
                self.scroll_by(1)
            elif zone == "more" and i >= 0:
                cr = self.cover_rect(i)
                self.menuRequested.emit(self.items[i]["key"], self.mapToGlobal(QPoint(int(cr.right() - 20), int(cr.top() + 40))))
            elif i >= 0:
                self.playRequested.emit(self.items[i]["key"])
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton and i >= 0:
            self.menuRequested.emit(self.items[i]["key"], self.mapToGlobal(e.position().toPoint()))
            e.accept()

    # -- painting ---------------------------------------------------------------------------------
    def paintEvent(self, e):
        host = self.host
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # header
        p.setFont(self.f_small)
        p.setPen(ink(0.5))
        p.drawText(QPointF(8, 14), self.subtitle)
        p.setFont(self.f_title)
        p.setPen(ink(0.97))
        fm = QFontMetrics(self.f_title)
        p.drawText(QPointF(8, 40), fm.elidedText(self.title, Qt.TextElideMode.ElideRight, self.width() - 16))
        # cards
        p.save()
        p.setClipRect(QRectF(0, HEAD_H - 4, self.width(), self.height() - HEAD_H + 4))
        fn, fa = QFontMetrics(self.f_name), QFontMetrics(self.f_art)
        first = max(0, int((self.offset - 4) // (CARD_W + GAP)))
        last = min(len(self.items), int((self.offset + self.width()) // (CARD_W + GAP)) + 2)
        for i in range(first, last):
            it = self.items[i]
            key = it["key"]
            cr = self.cover_rect(i)
            card = self.card_rect(i)
            hov = i == self.hover
            is_cur = key == host.current_path or host.lib.downloads.get(key, "\0") == host.current_path
            playing = is_cur and host.engine.playing
            if hov or is_cur:
                p.fillPath(round_path(card.adjusted(0, 0, 0, 0), 14), alpha(T.c1, 0.14) if is_cur else ink(0.07))
            pm = host.remote_images.get(it.get("thumb_url", ""), 300)
            self._cover(p, cr, key, pm)
            if is_cur:
                p.setBrush(NOBRUSH)
                p.setPen(QPen(alpha(T.c1, 0.85), 2))
                p.drawPath(round_path(cr.adjusted(1, 1, -1, -1), 11))
            if hov or is_cur:
                pb = QRectF(cr.right() - 52, cr.bottom() - 52, 44, 44)
                p.setPen(NOPEN)
                p.setBrush(T.c1)
                p.drawEllipse(pb.adjusted(0, 0, 0, 0))
                if is_cur and not hov:
                    draw_mini_bars(p, QRectF(pb.center().x() - 8, pb.center().y() - 8, 16, 16), host.engine, T.on_accent, playing, 3)
                else:
                    icon = "pause" if playing else "play"
                    off = 1.5 if icon == "play" else 0
                    draw_icon(p, icon, QRectF(pb.center().x() - 9 + off, pb.center().y() - 9, 18, 18), T.on_accent)
            if hov:
                mb = QRectF(cr.right() - 38, cr.top() + 6, 32, 32)
                p.setPen(NOPEN)
                p.setBrush(QColor(0, 0, 0, 140))
                p.drawEllipse(mb)
                draw_icon(p, "more", QRectF(mb.center().x() - 10, mb.center().y() - 10, 20, 20), QColor(255, 255, 255))
            tx = cr.left()
            tw = int(CARD_W - 16)
            p.setFont(self.f_name)
            p.setPen((T.c1.lighter(130) if T.dark else T.c1.darker(120)) if is_cur else ink(0.96))
            p.drawText(QPointF(tx, cr.bottom() + 20), fn.elidedText(it["title"], Qt.TextElideMode.ElideRight, tw))
            p.setFont(self.f_art)
            p.setPen(ink(0.55))
            p.drawText(QPointF(tx, cr.bottom() + 38), fa.elidedText(it.get("artist") or "Unknown artist",
                                                                    Qt.TextElideMode.ElideRight, tw))
        p.restore()
        # arrows on both sides
        if self.inside:
            can_l, can_r = self.arrows()
            for left, can in ((True, can_l), (False, can_r)):
                if not can:
                    continue
                r = self.arrow_rect(left)
                hov = self.hover_zone == ("arrow-left" if left else "arrow-right")
                p.setPen(QPen(ink(0.16), 1))
                p.setBrush(QColor(18, 20, 30, 235 if hov else 205) if T.dark else QColor(255, 255, 255, 240 if hov else 220))
                p.drawEllipse(r)
                draw_icon(p, "chevron-left" if left else "chevron-right",
                          QRectF(r.center().x() - 10, r.center().y() - 10, 20, 20), ink(1.0 if hov else 0.85))
        p.end()

    @staticmethod
    def _cover(p, rect, key, pm):
        """Square cover: a wide video thumbnail is cropped from the middle instead of squeezed."""
        if pm is None or pm.isNull():
            draw_thumb(p, rect, key, None)
            return
        w, h = pm.width(), pm.height()
        side = min(w, h)
        src = QRectF((w - side) / 2.0, (h - side) / 2.0, side, side)
        p.save()
        p.setClipPath(round_path(rect, 12))
        p.drawPixmap(rect, pm, src)
        p.restore()
        p.setBrush(NOBRUSH)
        p.setPen(QPen(ink(0.10), 1))
        p.drawPath(round_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12))


class ShelvesView(QScrollArea):
    """Vertical page that holds the shelves."""
    playRequested = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.body = QWidget()
        self.body.setAutoFillBackground(False)
        self.body.setStyleSheet("background: transparent;")
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 0, 6, 16)
        self.lay.setSpacing(8)
        self.lay.addStretch(1)
        self.setWidget(self.body)
        self.shelves = []

    def set_shelves(self, shelves):
        for s in self.shelves:
            s.setParent(None)
            s.deleteLater()
        self.shelves = []
        for title, sub, items in shelves:
            sh = Shelf(self.host, title, sub, items)
            sh.playRequested.connect(self.playRequested)
            sh.menuRequested.connect(self.menuRequested)
            self.lay.insertWidget(self.lay.count() - 1, sh)
            self.shelves.append(sh)
        self.verticalScrollBar().setValue(0)

    def repaint_all(self):
        for s in self.shelves:
            s.update()
