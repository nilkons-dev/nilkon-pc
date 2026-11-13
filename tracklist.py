"""Track list: one custom-painted row per song (no table cells -> no seams).

Row layout:  [play button] [cover] title / artist ......... album   [heart] duration [...]
Rows can be dragged to reorder (when the list is not filtered).
"""
from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QAbstractItemView, QWidget, QStyle

from icons import draw_icon
from theme import T, alpha, white, ink, hsv, hue_for, nice_time, text_baseline
from visuals import draw_mini_bars
from widgets import ui_font, round_path, NOPEN, NOBRUSH, AA

ROW_H = 60
PLAY_W = 64
HEART_W = 46
DUR_W = 62
MORE_W = 46


def row_zones(rect):
    """Column rectangles for a row rect (QRectF). Shared by painting, hit-testing and the header."""
    r = QRectF(rect)
    right = r.right() - 8
    more = QRectF(right - MORE_W, r.top(), MORE_W, r.height())
    dur = QRectF(more.left() - DUR_W, r.top(), DUR_W, r.height())
    heart = QRectF(dur.left() - HEART_W, r.top(), HEART_W, r.height())
    play = QRectF(r.left() + 10, r.top(), PLAY_W, r.height())
    body = QRectF(play.right(), r.top(), heart.left() - play.right() - 6, r.height())
    album_w = max(0.0, min(260.0, body.width() * 0.34)) if body.width() > 520 else 0.0
    album = QRectF(body.right() - album_w, r.top(), album_w, r.height())
    title = QRectF(body.left(), r.top(), body.width() - album_w - (10 if album_w else 0), r.height())
    return {"play": play, "title": title, "album": album, "heart": heart, "dur": dur, "more": more}


def draw_thumb(p, rect, path, cover, icon_alpha=0.85):
    """Rounded cover thumbnail with a crisp 1px border (generated gradient when there is no art)."""
    radius = rect.width() * 0.24
    clip = round_path(rect, radius)
    p.save()
    p.setClipPath(clip)
    if cover is not None and not cover.isNull():
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(rect, cover, QRectF(cover.rect()))
    else:
        h = hue_for(path)
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, hsv(0.58 + 0.08 * ((h * 7) % 1.0), 0.65, 0.78))
        g.setColorAt(1.0, hsv(0.64 + 0.06 * ((h * 5) % 1.0), 0.78, 0.38))
        p.fillRect(rect, QBrush(g))
        isz = rect.width() * 0.46
        draw_icon(p, "music", QRectF(rect.center().x() - isz / 2, rect.center().y() - isz / 2, isz, isz), white(icon_alpha))
    p.restore()
    p.setBrush(NOBRUSH)
    p.setPen(QPen(QColor(255, 255, 255, 46) if T.dark else QColor(12, 20, 44, 50), 1))
    p.drawPath(round_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius))


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, host, view):
        super().__init__(view)
        self.host = host
        self.f_title = ui_font(14, QFont.Weight.DemiBold)
        self.f_sub = ui_font(12, QFont.Weight.Normal)
        self.f_col = ui_font(13, QFont.Weight.Normal)

    def sizeHint(self, option, index):
        return QSize(40, ROW_H)

    def paint(self, p, option, index):
        host = self.host
        path = index.data(Qt.ItemDataRole.UserRole)
        rect = QRectF(option.rect)
        view = option.widget
        is_cur = host.is_cur(path)
        hover = view is not None and getattr(view, "hover_row", -1) == index.row()
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        playing_now = is_cur and host.engine.playing
        z = row_zones(rect.adjusted(0, 0, 0, 0))
        p.save()
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        pill = round_path(rect.adjusted(4, 3, -4, -3), 16)
        if is_cur:
            p.fillPath(pill, alpha(T.c1, 0.16))
        elif sel:
            p.fillPath(pill, ink(0.09))
        elif hover:
            p.fillPath(pill, ink(0.06))
        if is_cur or sel or hover:
            p.setBrush(NOBRUSH)
            p.setPen(QPen(alpha(T.c1, 0.42) if is_cur else ink(0.10), 1))
            p.drawPath(round_path(rect.adjusted(4.5, 3.5, -4.5, -3.5), 15.5))

        cy = rect.center().y()
        # play / pause button
        pb = z["play"]
        bx = QRectF(pb.left() + 6, cy - 15, 30, 30)
        if hover or is_cur:
            fill = alpha(T.c1, 0.95 if hover else 0.30)
            p.setPen(NOPEN)
            p.setBrush(fill)
            p.drawEllipse(bx)
            col = T.on_accent if hover else (T.c1.lighter(125) if T.dark else T.c1.darker(120))
            if is_cur and not hover:
                draw_mini_bars(p, QRectF(bx.center().x() - 7, bx.center().y() - 7, 14, 14), host.engine,
                               col, playing_now, 3)
            else:
                icon = "pause" if playing_now else "play"
                isz = 14.0
                off = 1.0 if icon == "play" else 0.0
                draw_icon(p, icon, QRectF(bx.center().x() - isz / 2 + off, bx.center().y() - isz / 2, isz, isz), col)
        else:
            p.setFont(self.f_col)
            p.setPen(ink(0.46))
            txt = str(index.row() + 1)
            fm = QFontMetrics(self.f_col)
            p.drawText(QPointF(bx.center().x() - fm.horizontalAdvance(txt) / 2.0, text_baseline(fm, rect.top(), rect.height())), txt)
        if hover and getattr(view, "can_drag", False):
            draw_icon(p, "grip", QRectF(rect.left() + 6, cy - 7, 12, 14), ink(0.32))

        # cover + texts
        ts = 42.0
        tr = QRectF(z["title"].left(), cy - ts / 2, ts, ts)
        draw_thumb(p, tr, path, host.thumb_for(path))
        x = tr.right() + 14
        avail = int(max(20, z["title"].right() - x - 6))
        title = host.lib.title(path)
        sub = host.lib.artist(path)
        fm1, fm2 = QFontMetrics(self.f_title), QFontMetrics(self.f_sub)
        p.setFont(self.f_title)
        p.setPen((T.c1.lighter(130) if T.dark else T.c1.darker(120)) if is_cur else ink(0.96))
        p.drawText(QPointF(x, cy - 3), fm1.elidedText(title, Qt.TextElideMode.ElideRight, avail))
        p.setFont(self.f_sub)
        p.setPen(ink(0.55))
        p.drawText(QPointF(x, cy + 15), fm2.elidedText(sub, Qt.TextElideMode.ElideRight, avail))

        if z["album"].width() > 10:
            fm = QFontMetrics(self.f_col)
            p.setFont(self.f_col)
            p.setPen(ink(0.58))
            p.drawText(QPointF(z["album"].left(), text_baseline(fm, rect.top(), rect.height())),
                       fm.elidedText(host.lib.album(path), Qt.TextElideMode.ElideRight, int(z["album"].width())))

        # heart
        liked = host.lib.is_liked(path)
        hr = z["heart"]
        isz = 19.0
        r = QRectF(hr.center().x() - isz / 2, cy - isz / 2, isz, isz)
        if liked:
            draw_icon(p, "heart-fill", r, hsv(0.96, 0.55, 1.0))
        elif hover or is_cur:
            draw_icon(p, "heart", r, ink(0.55))

        # duration
        dur = host.lib.duration(path)
        txt = nice_time(dur) if dur else "—"
        fm = QFontMetrics(self.f_col)
        p.setFont(self.f_col)
        p.setPen(ink(0.58))
        dr = z["dur"]
        p.drawText(QPointF(dr.center().x() - fm.horizontalAdvance(txt) / 2.0, text_baseline(fm, rect.top(), rect.height())), txt)

        # three-dot menu button
        mr = z["more"]
        mb = QRectF(mr.center().x() - 16, cy - 16, 32, 32)
        if hover or is_cur or sel:
            if view is not None and getattr(view, "more_hover", -1) == index.row():
                p.setPen(NOPEN)
                p.setBrush(ink(0.14))
                p.drawEllipse(mb)
            draw_icon(p, "more", QRectF(mb.center().x() - 10, cy - 10, 20, 20), ink(0.80 if hover else 0.55))
        p.restore()


class TrackList(QListWidget):
    """List of songs. Emits intent signals; the main window decides what they do."""
    playRequested = Signal(str)        # play button / double click
    likeRequested = Signal(str)
    menuRequested = Signal(str, object)  # path, global QPoint
    orderChanged = Signal(list)        # paths in their new order (after a drag)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.hover_row = -1
        self.more_hover = -1
        self.can_drag = False
        self._press_pos = None
        self.setObjectName("trackList")
        self.setItemDelegate(TrackDelegate(host, self))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setUniformItemSizes(True)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context)
        self.set_reorder_enabled(False)
        self.model().rowsMoved.connect(self._rows_moved)

    # -- configuration ---------------------------------------------------------------
    def set_reorder_enabled(self, enabled):
        self.can_drag = bool(enabled)
        if enabled:
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.setDropIndicatorShown(True)
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.setDropIndicatorShown(False)
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def paths(self):
        out = []
        for i in range(self.count()):
            out.append(self.item(i).data(Qt.ItemDataRole.UserRole))
        return out

    def _rows_moved(self, *_args):
        self.orderChanged.emit(self.paths())

    # -- hit testing -----------------------------------------------------------------
    def _hit(self, pos):
        """-> (item, zone name) for a viewport position."""
        item = self.itemAt(pos)
        if item is None:
            return None, ""
        rect = self.visualItemRect(item)
        z = row_zones(QRectF(rect))
        cy = rect.center().y()
        px, py = pos.x(), pos.y()
        pb = z["play"]
        if QRectF(pb.left() + 2, cy - 19, 38, 38).contains(px, py):
            return item, "play"
        if z["heart"].contains(px, py):
            return item, "heart"
        if QRectF(z["more"].center().x() - 19, cy - 19, 38, 38).contains(px, py):
            return item, "more"
        return item, "row"

    # -- events ----------------------------------------------------------------------
    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        item, zone = self._hit(pos)
        row = self.row(item) if item is not None else -1
        more = row if zone == "more" else -1
        if row != self.hover_row or more != self.more_hover:
            self.hover_row, self.more_hover = row, more
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row = self.more_hover = -1
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            item, zone = self._hit(e.position().toPoint())
            if item is not None and zone in ("play", "heart", "more"):
                path = item.data(Qt.ItemDataRole.UserRole)
                if zone == "play":
                    self.playRequested.emit(path)
                elif zone == "heart":
                    self.likeRequested.emit(path)
                else:
                    rect = self.visualItemRect(item)
                    z = row_zones(QRectF(rect))
                    gp = self.viewport().mapToGlobal(QPoint(int(z["more"].center().x()), int(rect.bottom() - 10)))
                    self.menuRequested.emit(path, gp)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        item, zone = self._hit(e.position().toPoint())
        if item is not None and zone == "row":
            self.playRequested.emit(item.data(Qt.ItemDataRole.UserRole))
            e.accept()
            return
        if zone in ("play", "heart", "more"):
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.playRequested.emit(item.data(Qt.ItemDataRole.UserRole))
                return
        super().keyPressEvent(e)

    def _context(self, pos):
        item = self.itemAt(pos)
        if item is not None:
            self.setCurrentItem(item)
            self.menuRequested.emit(item.data(Qt.ItemDataRole.UserRole), self.viewport().mapToGlobal(pos))


class ColumnHeader(QWidget):
    """TITLE / ALBUM / TIME captions aligned with the list rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self._inset = 0
        self._font = ui_font(10, QFont.Weight.ExtraBold)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)

    def set_inset(self, px):
        """Right inset = width of the list's scrollbar so columns line up."""
        if px != self._inset:
            self._inset = max(0, int(px))
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(0, 0, self.width() - self._inset, self.height())
        z = row_zones(r)
        fm = QFontMetrics(self._font)
        p.setFont(self._font)
        p.setPen(ink(0.42))
        base = text_baseline(fm, 0, r.height() - 2)
        p.drawText(QPointF(z["play"].left() + 14, base), "#")
        p.drawText(QPointF(z["title"].left(), base), "TITLE")
        if z["album"].width() > 10:
            p.drawText(QPointF(z["album"].left(), base), "ALBUM")
        d = z["dur"]
        p.drawText(QPointF(d.center().x() - fm.horizontalAdvance("TIME") / 2.0, base), "TIME")
        p.setPen(QPen(ink(0.10), 1))
        p.drawLine(QPointF(8, r.height() - 1), QPointF(r.width() - 8, r.height() - 1))
