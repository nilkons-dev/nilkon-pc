"""Small painted pieces used by the main window: logo, queue rows, playlist rows."""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QSize
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QPixmap, QPen, QColor
from PySide6.QtWidgets import QWidget, QStyledItemDelegate, QStyle, QListWidget

from cat_widgets import CatLogo
from icons import draw_icon
from theme import T, alpha, ink, text_baseline
from tracklist import draw_thumb
from visuals import draw_mini_bars
from widgets import ui_font, round_path, NOBRUSH, NOPEN, AA

ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


LogoMark = CatLogo          # the animated cat logo (kept under the old name for existing call sites)


class WordMark(QWidget):
    """The NILKON wordmark image (user supplied) at a given height."""

    def __init__(self, height=40, parent=None):
        super().__init__(parent)
        self._pm = QPixmap(str(ASSETS / "wordmark.png"))
        if self._pm.isNull():
            self.setFixedSize(120, height)
        else:
            self.setFixedSize(int(height * self._pm.width() / self._pm.height()), height)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        if self._pm.isNull():
            p.setPen(ink(0.95))
            p.setFont(ui_font(18, QFont.Weight.Bold))
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter, "NILKON")
            return
        if not T.dark:                                    # the wordmark has white details: keep them visible
            p.setPen(NOPEN)
            p.setBrush(QColor(15, 19, 24))
            p.drawRoundedRect(r, 8, 8)
            r = r.adjusted(5, 3, -5, -3)
        p.drawPixmap(r, self._pm, QRectF(self._pm.rect()))


class QueueDelegate(QStyledItemDelegate):
    def __init__(self, host, view):
        super().__init__(view)
        self.host = host
        self.f_title = ui_font(13, QFont.Weight.DemiBold)
        self.f_sub = ui_font(11, QFont.Weight.Normal)

    def sizeHint(self, option, index):
        return QSize(100, 54)

    def paint(self, p, option, index):
        host = self.host
        path = index.data(Qt.ItemDataRole.UserRole)
        rect = QRectF(option.rect)
        is_cur = host.is_cur(path)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        row = round_path(rect.adjusted(2, 2, -2, -2), 13)
        if is_cur:
            p.fillPath(row, alpha(T.c1, 0.16))
        elif hover:
            p.fillPath(row, ink(0.07))
        cy = rect.center().y()
        ts = 36.0
        tr = QRectF(rect.left() + 8, cy - ts / 2, ts, ts)
        draw_thumb(p, tr, path, host.thumb_for(path), 0.8)
        x = tr.right() + 11
        view = option.widget
        more_hover = view is not None and getattr(view, "hover_row", -1) == index.row()
        avail = int(max(20, rect.right() - x - (58 if is_cur else 36 if more_hover else 12)))
        fm1, fm2 = QFontMetrics(self.f_title), QFontMetrics(self.f_sub)
        p.setFont(self.f_title)
        p.setPen(T.c1.lighter(125) if (is_cur and T.dark) else T.c1.darker(110) if is_cur else ink(0.92))
        p.drawText(QPointF(x, cy - 2), fm1.elidedText(host.lib.title(path), Qt.TextElideMode.ElideRight, avail))
        p.setFont(self.f_sub)
        p.setPen(ink(0.52))
        p.drawText(QPointF(x, cy + 14), fm2.elidedText(host.lib.artist(path), Qt.TextElideMode.ElideRight, avail))
        if is_cur:
            draw_mini_bars(p, QRectF(rect.right() - 50, cy - 7, 14, 14), host.engine, T.c1, host.engine.playing, 3)
        if more_hover or is_cur:
            mb = QRectF(rect.right() - 32, cy - 13, 26, 26)
            if getattr(view, "more_hover", False) and more_hover:
                p.setPen(NOPEN)
                p.setBrush(ink(0.14))
                p.drawEllipse(mb)
            draw_icon(p, "more", QRectF(mb.center().x() - 9, cy - 9, 18, 18), ink(0.85 if more_hover else 0.5))
        p.restore()


class QueueList(QListWidget):
    """'Up next' list: double-click plays, the ⋯ button or a right-click opens the song menu."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.hover_row = -1
        self.more_hover = False
        self.setItemDelegate(QueueDelegate(host, self))
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context)

    def _on_more(self, item, pos):
        rect = self.visualItemRect(item)
        return pos.x() >= rect.right() - 36

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        item = self.itemAt(pos)
        row = self.row(item) if item is not None else -1
        more = item is not None and self._on_more(item, pos)
        if row != self.hover_row or more != self.more_hover:
            self.hover_row, self.more_hover = row, more
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row, self.more_hover = -1, False
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            item = self.itemAt(pos)
            if item is not None and self._on_more(item, pos):
                rect = self.visualItemRect(item)
                self._menu(item, self.viewport().mapToGlobal(QPoint(rect.right() - 20, rect.bottom() - 6)))
                e.accept()
                return
        super().mousePressEvent(e)

    def _context(self, pos):
        item = self.itemAt(pos)
        if item is not None:
            self._menu(item, self.viewport().mapToGlobal(pos))

    def _menu(self, item, global_pos):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.host.song_menu(path, global_pos)


class PlaylistDelegate(QStyledItemDelegate):
    """Sidebar playlist rows. UserRole = name, UserRole+1 = song count."""

    def __init__(self, host, view):
        super().__init__(view)
        self.host = host
        self.f = ui_font(13, QFont.Weight.DemiBold)
        self.f2 = ui_font(11, QFont.Weight.Normal)

    def sizeHint(self, option, index):
        return QSize(100, 42)

    def paint(self, p, option, index):
        rect = QRectF(option.rect)
        name = index.data(Qt.ItemDataRole.UserRole)
        count = index.data(Qt.ItemDataRole.UserRole + 1)
        sel = name == getattr(self.host, "current_collection", None) and self.host.page == "collection"
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        row = round_path(rect.adjusted(1, 2, -1, -2), 12)
        if sel:
            p.fillPath(row, alpha(T.c1, 0.18))
            p.setBrush(NOBRUSH)
            p.setPen(QPen(alpha(T.c1, 0.38), 1))
            p.drawPath(row)
        elif hover:
            p.fillPath(row, ink(0.07))
        cy = rect.center().y()
        accent = T.c1.lighter(120) if T.dark else T.c1.darker(115)
        draw_icon(p, "list-music", QRectF(rect.left() + 12, cy - 8, 16, 16), accent if sel else ink(0.60))
        fm, fm2 = QFontMetrics(self.f), QFontMetrics(self.f2)
        ctxt = str(count if count is not None else "")
        cw = fm2.horizontalAdvance(ctxt)
        p.setFont(self.f2)
        p.setPen(ink(0.45))
        p.drawText(QPointF(rect.right() - 12 - cw, text_baseline(fm2, rect.top(), rect.height())), ctxt)
        p.setFont(self.f)
        p.setPen(ink(0.98) if sel else ink(0.78))
        p.drawText(QPointF(rect.left() + 38, text_baseline(fm, rect.top(), rect.height())),
                   fm.elidedText(str(name), Qt.TextElideMode.ElideRight, int(max(20, rect.width() - 38 - cw - 24))))
        p.restore()
