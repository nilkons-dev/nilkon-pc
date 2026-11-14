"""Frameless glass dialogs: base class plus prompt / confirm / notice helpers."""
from PySide6.QtCore import Qt, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QApplication

from icons import qicon
from theme import T
from widgets import paint_glass, GButton, NOPEN, AA

SHADOW = 22


class GlassDialog(QDialog):
    """Translucent, shadowed, draggable (by its header) window with the glass look."""
    DRAG_HEIGHT = 92

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setModal(True)
        self._drag_off = None

    def showEvent(self, e):
        super().showEvent(e)
        self._center_on_parent()

    def _center_on_parent(self):
        host = self.parentWidget().window() if self.parentWidget() is not None else None
        if host is not None and host.isVisible():
            c = host.frameGeometry().center()
        else:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            c = screen.availableGeometry().center()
        self.move(c - QPoint(self.width() // 2, self.height() // 2))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(AA)
        r = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        p.setPen(NOPEN)
        for i in range(1, 17):
            p.setBrush(QColor(0, 0, 0, int(10 * (1 - i / 17.0) ** 1.5) + 1))
            p.drawRoundedRect(r.adjusted(-i, -i + 8, i, i + 8), 14 + i, 14 + i)
        p.setBrush(QColor(14, 17, 24, 255) if T.dark else QColor(250, 251, 254, 255))
        p.drawRoundedRect(r, 14, 14)
        paint_glass(p, r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 0.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < SHADOW + self.DRAG_HEIGHT:
            self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_off is not None:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None


class _SmallDialog(GlassDialog):
    """Header (icon + title + message) with room for a body and a button row."""

    def __init__(self, parent, title, message, icon, width=480):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(SHADOW + 30, SHADOW + 26, SHADOW + 30, SHADOW + 24)
        self.body.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(14)
        ic = QLabel()
        ic.setFixedSize(46, 46)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(qicon(icon, T.c1.lighter(120) if T.dark else T.c1.darker(115), 24).pixmap(24, 24))
        ic.setObjectName("dlgBadge")
        head.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("dlgTitle")
        tv.addWidget(t)
        if message:
            m = QLabel(message)
            m.setObjectName("dlgText")
            m.setWordWrap(True)
            tv.addWidget(m)
        head.addLayout(tv, 1)
        self.body.addLayout(head)

    def add_buttons(self, ok_text, ok_icon, cancel_text="Cancel", danger=False):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        if cancel_text:
            cancel = GButton(cancel_text, None, "glass")
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
        self.ok_btn = GButton(ok_text, ok_icon, "primary", 16)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.ok_btn)
        self.body.addSpacing(4)
        self.body.addLayout(row)


class PromptDialog(_SmallDialog):
    def __init__(self, parent, title, message, text="", placeholder="", ok_text="Save", icon="edit", max_len=80):
        super().__init__(parent, title, message, icon)
        self.field = QLineEdit(text)
        self.field.setObjectName("dlgInput")
        self.field.setPlaceholderText(placeholder)
        self.field.setMaxLength(max_len)
        self.field.setClearButtonEnabled(True)
        self.field.returnPressed.connect(self.accept)
        self.body.addWidget(self.field)
        self.add_buttons(ok_text, "check")

    def showEvent(self, e):
        super().showEvent(e)
        self.field.setFocus()
        self.field.selectAll()


class ConfirmDialog(_SmallDialog):
    def __init__(self, parent, title, message, ok_text="OK", icon="info", cancel_text="Cancel"):
        super().__init__(parent, title, message, icon)
        self.add_buttons(ok_text, "check" if icon != "trash" else "trash", cancel_text)


def ask_text(parent, title, message, text="", placeholder="", ok_text="Save", icon="edit", max_len=80):
    """-> (text, ok)"""
    dlg = PromptDialog(parent, title, message, text, placeholder, ok_text, icon, max_len)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return dlg.field.text(), ok


def confirm(parent, title, message, ok_text="OK", icon="info"):
    return ConfirmDialog(parent, title, message, ok_text, icon).exec() == QDialog.DialogCode.Accepted


def notice(parent, title, message, icon="info"):
    ConfirmDialog(parent, title, message, "OK", icon, cancel_text=None).exec()
