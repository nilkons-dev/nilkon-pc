"""Custom window title bar: flat, quiet and theme-aware (the window itself has no system frame).

Drag the bar to move the window (Windows snap works), double-click to maximise / restore, right-click for the window
menu. The colours follow the player theme, so the bar always matches the song colours and dark / light mode.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from theme import T, alpha, ink, surface

BAR_H = 38
BTN_W = 46
BTN_H = BAR_H
RADIUS = 14
CLOSE_RED = QColor(232, 72, 85)


class TitleBar(QWidget):
    toggleMaximize = Signal()

    def __init__(self, window, icon, parent=None):
        super().__init__(parent)
        self._win = window
        self._icon = icon
        self._title = ""
        self._hover = -1               # 0 minimise, 1 maximise, 2 close
        self._down = -1
        self.setFixedHeight(BAR_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # -- state ----------------------------------------------------------------------------
    def set_title(self, text):
        if text != self._title:
            self._title = text
            self.update()

    def _maximized(self):
        return self._win.isMaximized() or self._win.isFullScreen()

    def _button_rects(self):
        right = float(self.width())
        rects = []
        for i in (2, 1, 0):
            rects.append((i, QRectF(right - BTN_W, 0, BTN_W, BTN_H)))
            right -= BTN_W
        return dict(rects), right

    def _button_at(self, pos):
        rects, _ = self._button_rects()
        for i, r in rects.items():
            if r.contains(QPointF(pos)):
                return i
        return -1

    # -- painting -------------------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, self.width(), self.height() + RADIUS * 2), RADIUS, RADIUS)
        p.setClipPath(clip)

        # flat strip with one hairline underneath
        p.fillRect(self.rect(), surface(0.34 if T.dark else 0.50))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), ink(0.07))

        # logo + name
        x = 14
        if self._icon is not None and not self._icon.isNull():
            pm = self._icon.pixmap(48, 48)
            if not pm.isNull():
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(QRectF(x, (self.height() - 18) / 2.0, 18, 18).toRect(), pm)
                x += 18 + 9
        f = QFont(self.font())
        f.setPointSizeF(8.6)
        f.setWeight(QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(f)
        p.setPen(ink(0.80))
        name = "NILKON"
        nm_w = QFontMetrics(f).horizontalAdvance(name)
        p.drawText(QRectF(x, 0, nm_w + 4, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        left_end = x + nm_w + 16

        # window buttons
        rects, buttons_left = self._button_rects()
        for i, br in rects.items():
            self._paint_button(p, i, br)

        # song title in the middle (kept clear of the name and the buttons)
        if self._title:
            f2 = QFont(self.font())
            f2.setPointSizeF(9.0)
            p.setFont(f2)
            fm = QFontMetrics(f2)
            avail = int(max(40, min(self.width() - 2 * max(left_end, self.width() - buttons_left + 8), 640)))
            if self.width() / 2.0 - avail / 2.0 < left_end or self.width() / 2.0 + avail / 2.0 > buttons_left - 8:
                avail = int(max(0, buttons_left - 12 - left_end))
                box = QRectF(left_end, 0, avail, self.height())
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            else:
                box = QRectF(self.width() / 2.0 - avail / 2.0, 0, avail, self.height())
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            if avail > 30:
                p.setPen(ink(0.55))
                p.drawText(box, align, fm.elidedText(self._title, Qt.TextElideMode.ElideRight, int(box.width())))
        p.end()

    def _paint_button(self, p, i, br):
        hot = self._hover == i
        down = self._down == i and hot
        close = i == 2
        if hot:
            if close:
                p.fillRect(br, QColor(CLOSE_RED.red(), CLOSE_RED.green(), CLOSE_RED.blue(), 215 if down else 255))
            else:
                p.fillRect(br, ink(0.12 if down else 0.075))
        col = QColor(255, 255, 255) if (hot and close) else ink(0.95 if hot else 0.66)
        pen = QPen(col, 1.15)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = br.center()
        s = 4.6
        if i == 0:
            p.drawLine(QPointF(c.x() - s, c.y() + 0.5), QPointF(c.x() + s, c.y() + 0.5))
        elif i == 1:
            if self._maximized():
                p.drawRect(QRectF(c.x() - s, c.y() - s + 2.0, 2 * s - 2.0, 2 * s - 2.0))
                path = QPainterPath()
                path.moveTo(c.x() - s + 2.0, c.y() - s + 2.0)
                path.lineTo(c.x() - s + 2.0, c.y() - s)
                path.lineTo(c.x() + s, c.y() - s)
                path.lineTo(c.x() + s, c.y() + s - 2.0)
                path.lineTo(c.x() + s - 2.0, c.y() + s - 2.0)
                p.drawPath(path)
            else:
                p.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
        else:
            d = s
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))

    # -- mouse ----------------------------------------------------------------------------
    def mouseMoveEvent(self, e):
        h = self._button_at(e.position())
        if h != self._hover:
            self._hover = h
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover != -1 or self._down != -1:
            self._hover = -1
            self._down = -1
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            b = self._button_at(e.position())
            if b >= 0:
                self._down = b
                self.update()
                return
            h = self._win.windowHandle()
            if h is not None and not self._win.isFullScreen():
                h.startSystemMove()
                return
        elif e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._down >= 0:
            b = self._button_at(e.position())
            down, self._down = self._down, -1
            self.update()
            if b == down:
                if down == 0:
                    self._win.showMinimized()
                elif down == 1:
                    self.toggleMaximize.emit()
                else:
                    self._win.close()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._button_at(e.position()) < 0:
            self.toggleMaximize.emit()
            return
        super().mouseDoubleClickEvent(e)

    def _menu(self, global_pos):
        m = QMenu(self)
        maxed = self._maximized()
        a_restore = m.addAction("Restore" if maxed else "Maximize")
        a_min = m.addAction("Minimize")
        m.addSeparator()
        a_close = m.addAction("Close")
        chosen = m.exec(global_pos)
        if chosen is a_restore:
            self.toggleMaximize.emit()
        elif chosen is a_min:
            self._win.showMinimized()
        elif chosen is a_close:
            self._win.close()


# -- edges: resize a frameless window -----------------------------------------------------------------
EDGE = 7


def edges_at(pos, width, height):
    """Which window edges (Qt.Edges) a point near the border belongs to."""
    e = Qt.Edge(0)
    if pos.x() <= EDGE:
        e |= Qt.Edge.LeftEdge
    elif pos.x() >= width - EDGE:
        e |= Qt.Edge.RightEdge
    if pos.y() <= EDGE:
        e |= Qt.Edge.TopEdge
    elif pos.y() >= height - EDGE:
        e |= Qt.Edge.BottomEdge
    return e


def cursor_for(edges):
    L, R, T_, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
    if edges in (L | T_, R | B):
        return Qt.CursorShape.SizeFDiagCursor
    if edges in (R | T_, L | B):
        return Qt.CursorShape.SizeBDiagCursor
    if edges in (L, R):
        return Qt.CursorShape.SizeHorCursor
    return Qt.CursorShape.SizeVerCursor
