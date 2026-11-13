"""Online page: live song search results with play, download and progress states."""
from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QStyledItemDelegate, QStackedWidget, QAbstractItemView)

from icons import draw_icon, qicon
from theme import T, alpha, ink, hsv, nice_time, text_baseline
from tracklist import draw_thumb
from visuals import draw_mini_bars
from widgets import GButton, ui_font, round_path, NOPEN, NOBRUSH, AA

ROW_H = 64
PLAY_W, DUR_W, DL_W, MORE_W = 64, 60, 52, 46


def zones(rect):
    r = QRectF(rect)
    right = r.right() - 8
    more = QRectF(right - MORE_W, r.top(), MORE_W, r.height())
    dl = QRectF(more.left() - DL_W, r.top(), DL_W, r.height())
    dur = QRectF(dl.left() - DUR_W, r.top(), DUR_W, r.height())
    play = QRectF(r.left() + 10, r.top(), PLAY_W, r.height())
    body = QRectF(play.right(), r.top(), dur.left() - play.right() - 6, r.height())
    return {"play": play, "body": body, "dur": dur, "dl": dl, "more": more}


class ResultDelegate(QStyledItemDelegate):
    def __init__(self, page, view):
        super().__init__(view)
        self.page = page
        self.f_title = ui_font(14, QFont.Weight.DemiBold)
        self.f_sub = ui_font(12, QFont.Weight.Normal)
        self.f_col = ui_font(13, QFont.Weight.Normal)

    def sizeHint(self, option, index):
        return QSize(40, ROW_H)

    def paint(self, p, option, index):
        page, host = self.page, self.page.host
        key = index.data(Qt.ItemDataRole.UserRole)
        item = host.online_items.get(key)
        if item is None:
            return
        rect = QRectF(option.rect)
        view = option.widget
        hover = view is not None and getattr(view, "hover_row", -1) == index.row()
        is_cur = key == host.current_path or host.lib.downloads.get(key, "\0") == host.current_path
        playing_now = is_cur and host.engine.playing
        loading = key == host.loading_key
        state = host.download_state(key)
        z = zones(rect)
        cy = rect.center().y()
        p.save()
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pill = round_path(rect.adjusted(4, 3, -4, -3), 16)
        if is_cur:
            p.fillPath(pill, alpha(T.c1, 0.16))
        elif hover:
            p.fillPath(pill, ink(0.06))
        if is_cur or hover:
            p.setBrush(NOBRUSH)
            p.setPen(QPen(alpha(T.c1, 0.42) if is_cur else ink(0.10), 1))
            p.drawPath(round_path(rect.adjusted(4.5, 3.5, -4.5, -3.5), 15.5))

        # play button
        bx = QRectF(z["play"].left() + 6, cy - 15, 30, 30)
        if hover or is_cur:
            p.setPen(NOPEN)
            p.setBrush(alpha(T.c1, 0.95 if hover else 0.30))
            p.drawEllipse(bx)
            col = T.on_accent if hover else (T.c1.lighter(125) if T.dark else T.c1.darker(120))
            if loading:
                draw_icon(p, "clock", QRectF(bx.center().x() - 8, bx.center().y() - 8, 16, 16), col)
            elif is_cur and not hover:
                draw_mini_bars(p, QRectF(bx.center().x() - 7, bx.center().y() - 7, 14, 14), host.engine, col, playing_now, 3)
            else:
                icon = "pause" if playing_now else "play"
                off = 1.0 if icon == "play" else 0.0
                draw_icon(p, icon, QRectF(bx.center().x() - 7 + off, bx.center().y() - 7, 14, 14), col)
        else:
            p.setFont(self.f_col)
            p.setPen(ink(0.46))
            txt = str(index.row() + 1)
            fm = QFontMetrics(self.f_col)
            p.drawText(QPointF(bx.center().x() - fm.horizontalAdvance(txt) / 2.0,
                               text_baseline(fm, rect.top(), rect.height())), txt)

        # thumbnail + text
        ts = 44.0
        tr = QRectF(z["body"].left(), cy - ts / 2, ts, ts)
        draw_thumb(p, tr, key, page.thumb(item))
        x = tr.right() + 14
        avail = int(max(20, z["body"].right() - x - 6))
        fm1, fm2 = QFontMetrics(self.f_title), QFontMetrics(self.f_sub)
        p.setFont(self.f_title)
        p.setPen((T.c1.lighter(130) if T.dark else T.c1.darker(120)) if is_cur else ink(0.96))
        p.drawText(QPointF(x, cy - 3), fm1.elidedText(item["title"], Qt.TextElideMode.ElideRight, avail))
        p.setFont(self.f_sub)
        sub, col = item["artist"] or "Unknown artist", ink(0.55)
        if state["state"] == "downloading":
            sub, col = f"Downloading… {int(state['pct'] * 100)}%", alpha(T.c1, 1.0)
        elif state["state"] == "queued":
            sub, col = "Waiting to download…", alpha(T.c1, 1.0)
        elif state["state"] == "error":
            sub, col = state.get("error") or "Download failed - click to retry", hsv(0.98, 0.55, 1.0)
        elif state["state"] == "done":
            sub, col = "In your library · " + (item["artist"] or ""), ink(0.6)
        p.setPen(col)
        p.drawText(QPointF(x, cy + 15), fm2.elidedText(sub, Qt.TextElideMode.ElideRight, avail))

        # duration
        if item["duration_ms"]:
            fm = QFontMetrics(self.f_col)
            p.setFont(self.f_col)
            p.setPen(ink(0.58))
            txt = nice_time(item["duration_ms"])
            p.drawText(QPointF(z["dur"].center().x() - fm.horizontalAdvance(txt) / 2.0,
                               text_baseline(fm, rect.top(), rect.height())), txt)

        # download button
        d = QRectF(z["dl"].center().x() - 16, cy - 16, 32, 32)
        st = state["state"]
        if st in ("downloading", "queued"):
            p.setBrush(NOBRUSH)
            p.setPen(QPen(ink(0.18), 2.4))
            p.drawEllipse(d.adjusted(3, 3, -3, -3))
            if st == "downloading":
                pen = QPen(T.c1, 2.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(d.adjusted(3, 3, -3, -3), 90 * 16, -int(360 * 16 * max(0.02, state["pct"])))
            draw_icon(p, "x", QRectF(d.center().x() - 5, d.center().y() - 5, 10, 10), ink(0.8))
        elif st == "done":
            p.setPen(NOPEN)
            p.setBrush(alpha(T.c1, 0.22))
            p.drawEllipse(d)
            draw_icon(p, "check", QRectF(d.center().x() - 8, d.center().y() - 8, 16, 16),
                      T.c1.lighter(125) if T.dark else T.c1.darker(115))
        else:
            if view is not None and getattr(view, "dl_hover", -1) == index.row():
                p.setPen(NOPEN)
                p.setBrush(ink(0.14))
                p.drawEllipse(d)
            if hover or is_cur or st == "error":
                draw_icon(p, "download" if st != "error" else "reset", QRectF(d.center().x() - 10, cy - 10, 20, 20),
                          ink(0.85) if st != "error" else hsv(0.98, 0.55, 1.0))
        # more
        if hover or is_cur:
            mb = QRectF(z["more"].center().x() - 16, cy - 16, 32, 32)
            if view is not None and getattr(view, "more_hover", -1) == index.row():
                p.setPen(NOPEN)
                p.setBrush(ink(0.14))
                p.drawEllipse(mb)
            draw_icon(p, "more", QRectF(mb.center().x() - 10, cy - 10, 20, 20), ink(0.80 if hover else 0.55))
        p.restore()


class ResultList(QListWidget):
    playRequested = Signal(str)
    downloadRequested = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.hover_row = self.dl_hover = self.more_hover = -1
        self.setItemDelegate(ResultDelegate(page, self))
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

    def _hit(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None, ""
        rect = self.visualItemRect(item)
        z = zones(QRectF(rect))
        cy = rect.center().y()
        px, py = pos.x(), pos.y()
        if QRectF(z["play"].left() + 2, cy - 19, 38, 38).contains(px, py):
            return item, "play"
        if QRectF(z["dl"].center().x() - 19, cy - 19, 38, 38).contains(px, py):
            return item, "dl"
        if QRectF(z["more"].center().x() - 19, cy - 19, 38, 38).contains(px, py):
            return item, "more"
        return item, "row"

    def mouseMoveEvent(self, e):
        item, zone = self._hit(e.position().toPoint())
        row = self.row(item) if item is not None else -1
        dl = row if zone == "dl" else -1
        more = row if zone == "more" else -1
        if (row, dl, more) != (self.hover_row, self.dl_hover, self.more_hover):
            self.hover_row, self.dl_hover, self.more_hover = row, dl, more
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row = self.dl_hover = self.more_hover = -1
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            item, zone = self._hit(e.position().toPoint())
            if item is not None and zone in ("play", "dl", "more"):
                key = item.data(Qt.ItemDataRole.UserRole)
                if zone == "play":
                    self.playRequested.emit(key)
                elif zone == "dl":
                    self.downloadRequested.emit(key)
                else:
                    rect = self.visualItemRect(item)
                    z = zones(QRectF(rect))
                    self.menuRequested.emit(key, self.viewport().mapToGlobal(
                        QPoint(int(z["more"].center().x()), int(rect.bottom() - 10))))
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        item, zone = self._hit(e.position().toPoint())
        if item is not None and zone == "row":
            self.playRequested.emit(item.data(Qt.ItemDataRole.UserRole))
            e.accept()
            return
        if zone:
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem() is not None:
            self.playRequested.emit(self.currentItem().data(Qt.ItemDataRole.UserRole))
            return
        super().keyPressEvent(e)

    def _context(self, pos):
        item = self.itemAt(pos)
        if item is not None:
            self.setCurrentItem(item)
            self.menuRequested.emit(item.data(Qt.ItemDataRole.UserRole), self.viewport().mapToGlobal(pos))


class OnlinePage(QWidget):
    playRequested = Signal(str)
    downloadRequested = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        title = QLabel("Online")
        title.setObjectName("sectionTitle")
        self.subtitle = QLabel("Search any song · stream instantly · download to listen offline")
        self.subtitle.setObjectName("muted")
        tv.addWidget(title)
        tv.addWidget(self.subtitle)
        head.addLayout(tv, 1)
        lay.addLayout(head)

        self.list = ResultList(self)
        self.list.playRequested.connect(self.playRequested)
        self.list.downloadRequested.connect(self.downloadRequested)
        self.list.menuRequested.connect(self.menuRequested)

        self.msg = QWidget()
        ml = QVBoxLayout(self.msg)
        ml.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ml.setSpacing(10)
        self.msg_icon = QLabel()
        self.msg_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_title = QLabel("")
        self.msg_title.setObjectName("emptyTitle")
        self.msg_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_text = QLabel("")
        self.msg_text.setObjectName("muted")
        self.msg_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_text.setWordWrap(True)
        self.msg_text.setMaximumWidth(520)
        self.retry = GButton("Try again", "reset", "primary", 16)
        self.retry.clicked.connect(host.retry_online_search)
        ml.addWidget(self.msg_icon)
        ml.addWidget(self.msg_title)
        ml.addWidget(self.msg_text, 0, Qt.AlignmentFlag.AlignHCenter)
        ml.addSpacing(6)
        ml.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.msg)
        lay.addWidget(self.stack, 1)
        self.show_message("idle")

    # -- state -----------------------------------------------------------------------------------
    def set_busy(self, busy):
        self.subtitle.setText("Searching…" if busy else "Search any song · stream instantly · download to listen offline")

    def thumb(self, item):
        return self.host.remote_images.get(item["thumb_url"], 120)

    def show_message(self, kind, text=""):
        icons = {"idle": "globe", "loading": "clock", "error": "info", "empty": "search"}
        titles = {"idle": "Find any song", "loading": "Searching…",
                  "error": "Couldn't search", "empty": "No songs found"}
        descs = {"idle": "Start typing a song or artist name in the search bar - results appear as you type.\n"
                         "Press ▶ to play. The player keeps playing similar songs after it.",
                 "loading": "Looking for the best matches…", "error": text,
                 "empty": "Check the spelling or try the artist name."}
        self.msg_icon.setPixmap(qicon(icons[kind], ink(0.45), 56).pixmap(56, 56))
        self.msg_title.setText(titles[kind])
        self.msg_text.setText(descs[kind])
        self.retry.setVisible(kind == "error")
        self.stack.setCurrentIndex(1)

    def set_results(self, items):
        self.list.clear()
        if not items:
            self.show_message("empty")
            return
        for it in items:
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, it["key"])
            self.list.addItem(li)
        self.stack.setCurrentIndex(0)
        self.list.scrollToTop()

    def repaint_rows(self):
        self.list.viewport().update()
