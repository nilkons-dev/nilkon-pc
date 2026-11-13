"""Home page: live-wave hero, recently played and 'suggested for you' song cards."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QPen, QLinearGradient, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QStackedLayout, QLabel, QFrame)

from icons import draw_icon
from theme import T, alpha, ink, surface
from tracklist import draw_thumb
from visuals import WaveField
from widgets import (GlassPanel, GButton, ElidedLabel, eyebrow, ui_font, round_path, NOPEN, NOBRUSH, AA)

CARD_W, CARD_H, CARD_GAP = 168, 214, 16


class SongCard(QWidget):
    clicked = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, host, path, parent=None):
        super().__init__(parent)
        self.host = host
        self.path = path
        self._hover = False
        self.setFixedSize(CARD_W, CARD_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(host.lib.title(path))
        self.f_t = ui_font(13, QFont.Weight.DemiBold)
        self.f_s = ui_font(11, QFont.Weight.Normal)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.path)
        elif e.button() == Qt.MouseButton.RightButton:
            self.menuRequested.emit(self.path, e.globalPosition().toPoint())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        host = self.host
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        is_cur = host.is_cur(self.path)
        card = round_path(r, 20)
        p.fillPath(card, alpha(T.c1, 0.14) if is_cur else ink(0.10 if self._hover else 0.05))
        p.setBrush(NOBRUSH)
        p.setPen(QPen(alpha(T.c1, 0.45) if is_cur else ink(0.14 if self._hover else 0.08), 1))
        p.drawPath(card)
        cover = QRectF(10, 10, CARD_W - 20, CARD_W - 20)
        draw_thumb(p, cover, self.path, host.thumb_for(self.path))
        if self._hover or is_cur:
            btn = QRectF(cover.right() - 46, cover.bottom() - 46, 38, 38)
            p.setPen(NOPEN)
            p.setBrush(T.c1)
            p.drawEllipse(btn)
            icon = "pause" if (is_cur and host.engine.playing) else "play"
            off = 1.2 if icon == "play" else 0.0
            draw_icon(p, icon, QRectF(btn.center().x() - 9 + off, btn.center().y() - 9, 18, 18), T.on_accent)
        fm1, fm2 = QFontMetrics(self.f_t), QFontMetrics(self.f_s)
        w = int(CARD_W - 24)
        p.setFont(self.f_t)
        p.setPen((T.c1.lighter(130) if T.dark else T.c1.darker(120)) if is_cur else ink(0.96))
        p.drawText(QPointF(12, cover.bottom() + 24), fm1.elidedText(host.lib.title(self.path), Qt.TextElideMode.ElideRight, w))
        p.setFont(self.f_s)
        p.setPen(ink(0.55))
        p.drawText(QPointF(12, cover.bottom() + 42), fm2.elidedText(host.lib.artist(self.path), Qt.TextElideMode.ElideRight, w))


class CardRow(QWidget):
    """Titled, single line of song cards that shows as many as fit the width."""
    cardClicked = Signal(str)
    cardMenu = Signal(str, object)

    def __init__(self, host, title, subtitle="", parent=None):
        super().__init__(parent)
        self.host = host
        self._cards = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("rowTitle")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("muted")
        tl.addWidget(self.title)
        tl.addWidget(self.sub)
        head.addLayout(tl)
        head.addStretch(1)
        self.action = None
        self.head = head
        lay.addLayout(head)
        self.strip = QWidget()
        self.strip.setFixedHeight(CARD_H)
        self.strip_lay = QHBoxLayout(self.strip)
        self.strip_lay.setContentsMargins(0, 0, 0, 0)
        self.strip_lay.setSpacing(CARD_GAP)
        self.placeholder = QLabel("")
        self.placeholder.setObjectName("muted")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.hide()
        lay.addWidget(self.strip)
        lay.addWidget(self.placeholder)

    def add_action(self, button):
        self.action = button
        self.head.addWidget(button)

    def set_paths(self, paths, placeholder=""):
        while self.strip_lay.count():          # also drops the old trailing stretch
            item = self.strip_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards = []
        for path in paths:
            c = SongCard(self.host, path)
            c.clicked.connect(self.cardClicked)
            c.menuRequested.connect(self.cardMenu)
            self.strip_lay.addWidget(c)
            self._cards.append(c)
        self.strip_lay.addStretch(1)
        self.strip.setVisible(bool(paths))
        self.placeholder.setText(placeholder)
        self.placeholder.setVisible(not paths)
        self.placeholder.setFixedHeight(70)
        self._fit()

    def _fit(self):
        n = max(1, int((self.width() + CARD_GAP) // (CARD_W + CARD_GAP)))
        for i, c in enumerate(self._cards):
            c.setVisible(i < n)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class HeroOverlay(QWidget):
    """Soft scrim so the title stays readable above the moving waves."""

    def paintEvent(self, _e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, surface(0.62))
        g.setColorAt(0.62, surface(0.34))
        g.setColorAt(1.0, surface(0.0))
        p.fillRect(self.rect(), QBrush(g))
        p.end()


class HomePage(QScrollArea):
    playMix = Signal()
    shuffleAll = Signal()
    refreshSuggestions = Signal()
    playPath = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("homeBody")
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(22)

        hero = GlassPanel(24, 0.40)
        hero.setFixedHeight(176)
        stack = QStackedLayout(hero)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.wave = WaveField(host.engine)
        stack.addWidget(self.wave)
        overlay = HeroOverlay()
        ol = QVBoxLayout(overlay)
        ol.setContentsMargins(28, 20, 28, 20)
        ol.setSpacing(4)
        self.hero_eyebrow = eyebrow("WELCOME")
        self.hero_title = ElidedLabel("Stay in your own frequency.")
        self.hero_title.setObjectName("heroTitle")
        self.hero_desc = ElidedLabel("")
        self.hero_desc.setObjectName("heroDesc")
        ol.addWidget(self.hero_eyebrow)
        ol.addWidget(self.hero_title)
        ol.addWidget(self.hero_desc)
        ol.addStretch(1)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.play_btn = GButton("Play my mix", "play", "primary", 16)
        self.play_btn.clicked.connect(self.playMix)
        self.shuffle_btn = GButton("Shuffle all", "shuffle", "glass", 16)
        self.shuffle_btn.clicked.connect(self.shuffleAll)
        btns.addWidget(self.play_btn)
        btns.addWidget(self.shuffle_btn)
        btns.addStretch(1)
        ol.addLayout(btns)
        stack.addWidget(overlay)
        overlay.raise_()
        lay.addWidget(hero)

        self.recent = CardRow(host, "Recently played", "Pick up where you left off")
        self.recent.cardClicked.connect(self.playPath)
        self.recent.cardMenu.connect(self.menuRequested)
        lay.addWidget(self.recent)

        self.suggest = CardRow(host, "Suggested for you", "A mix leaning towards the songs you play the most")
        refresh = GButton("Refresh", "shuffle", "ghost", 15)
        refresh.setToolTip("Pick a new set of suggestions")
        refresh.clicked.connect(self.refreshSuggestions)
        self.suggest.add_action(refresh)
        self.suggest.cardClicked.connect(self.playPath)
        self.suggest.cardMenu.connect(self.menuRequested)
        lay.addWidget(self.suggest)
        lay.addStretch(1)

    def set_hero(self, eyebrow_text, title, desc):
        self.hero_eyebrow.setText(eyebrow_text)
        self.hero_title.set_full_text(title)
        self.hero_desc.set_full_text(desc)
