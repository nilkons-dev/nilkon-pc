"""NILKON - a private, offline liquid-glass music player (PySide6 + python-vlc)."""
import copy
import gc
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import math
import random
import shutil
import os
import sys
import threading
import time as _time
import zlib
from datetime import datetime
from pathlib import Path

def _use_bundled_vlc():
    """The installed app carries its own copy of VLC (folder 'vlc' next to the program), so nothing else is needed."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    folder = base / "vlc"
    lib = folder / "libvlc.dll"
    if not lib.exists():
        return
    os.environ["PYTHON_VLC_LIB_PATH"] = str(lib)
    os.environ["PYTHON_VLC_MODULE_PATH"] = str(folder / "plugins")
    os.environ["VLC_PLUGIN_PATH"] = str(folder / "plugins")
    try:
        os.add_dll_directory(str(folder))
    except Exception:
        pass


_use_bundled_vlc()

try:
    import vlc
    VLC_ERROR = None
except Exception as _exc:  # reported nicely once the QApplication exists
    vlc = None
    VLC_ERROR = _exc

from collections import OrderedDict
from PySide6.QtCore import Qt, QEvent, QFile, QPropertyAnimation, QEasingCurve, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QColor, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QPixmap, QRadialGradient, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QLineEdit, QMessageBox, QAbstractItemView, QMenu, QStackedWidget, QSizePolicy)

import tags
from appinfo import APP_NAME
from analyzer_qt import TrackAnalyzer
from covers import CoverCache, pixmap_from_bytes, square_pixmap
from dialogs import ask_text, confirm, notice
from engine import VisualEngine
from eq_dialog import EqualizerDialog
from home import HomePage
from icons import qicon
from library import Library, ALL, LIKED, RECENT, is_online, effective_preamp
import crashlog
import online
from online import cleanup_partial, find_ffmpeg
from online_page import OnlinePage
from thread_bridge import Mailbox
from stream_proxy import StreamHub
from online_qt import OnlineJobs, RemoteImages
from presence import DiscordPresence
from cat_widgets import CatButton
from panels import LogoMark, WordMark, QueueList, PlaylistDelegate, ASSETS
from settings_dialog import SettingsDialog
from theme import T, ink, hue_for, nice_time, build_qss, FONT_FAMILIES
from tracklist import TrackList, ColumnHeader
from visuals import Turntable, MiniDisc, Spectrum, WaveField
from widgets import (AuroraBackground, GlassPanel, GButton, GlassSlider, SeekBar, Toast, ElidedLabel, eyebrow,
                     style_menu)

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
COLLECTION_TITLES = {ALL: "All tracks", LIKED: "Liked songs", RECENT: "Recently played"}
LISTEN_SECONDS = 15.0


def app_icon():
    icon = QIcon()
    for name in ("logo.ico", "logo_app.png"):
        f = ASSETS / name
        if f.is_file():
            icon.addFile(str(f))
    return icon


def cover_hue(pix):
    """Dominant hue (0..1) of a pixmap, or None for grey / empty art."""
    img = pix.toImage().scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    sx = sy = total = 0.0
    for y in range(img.height()):
        for x in range(img.width()):
            h, s, v, _a = img.pixelColor(x, y).getHsvF()
            if h < 0:
                continue
            w = s * s * v + 0.002
            sx += math.cos(h * 2 * math.pi) * w
            sy += math.sin(h * 2 * math.pi) * w
            total += w
    if total < 0.5 or (abs(sx) + abs(sy)) / total < 0.05:
        return None
    return (math.atan2(sy, sx) / (2 * math.pi)) % 1.0


# ------------------------------------------------------------------------------------
class MusicPlayer(QMainWindow):
    ytdlpUpdated = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1240, 780)
        self.setAcceptDrops(True)

        self.lib = Library().load()
        self.current_path = ""
        self.page = "home"                  # home | collection
        self.current_collection = ALL
        self.queue_paths = []
        self.queue_name = None
        self.shuffle = False
        self.repeat = "Off"
        self.cover_pix = None
        self._seeking = False
        self._req_t = 0.0
        self._pending_seek = None
        self._listen_acc = 0.0
        self._listen_done = False
        self._save_ticks = 0
        self._play_stack = []
        self._meta_done = deque()
        self._meta_inflight = set()
        self._meta_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nilkon-meta")
        self._bg_cache = {}
        self._suggest = []
        self._pre_mute = 75
        self._vlc_eq = None
        self._hero_state = None
        self.online_items = {}              # key -> item dict (search results and streamed songs)
        self.online_results = []
        self.dl_states = {}
        self.loading_key = ""
        self.last_online_query = ""
        self._search_token = 0
        self._analysis_target = ""
        self._stream_url = ""
        self._cache_tried = False
        self._presence_sig = None
        self.radio_seed = ""                # key of the song the automatic "related songs" queue grew from
        self.radio_on = False
        self._radio_busy = False
        self._shuf_done = set()
        self._retried = set()
        self._radio_wait = False
        self._mb = Mailbox(self)
        self._net_wait_key = ""
        self._net_wait_pos = 0
        self._net_ticks = 0
        self._net_cycles = {}
        self._search_wait = False
        self._buf_t = 0.0
        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(lambda: self.jobs.check_network())
        self._search_cache = OrderedDict()
        self._error_count = 0
        for k, it in self.lib.online_meta.items():
            self.online_items[k] = dict(it)

        _args = ["--no-video", "--quiet"]
        if self.lib.settings.get("normalize"):
            _args += ["--audio-filter=normvol", "--norm-buff-size=20", "--norm-max-level=2.0"]
        try:
            self.instance = vlc.Instance(*_args)
        except Exception:
            self.instance = vlc.Instance("--no-video", "--quiet")
        self.player = self.instance.media_player_new()
        self.engine = VisualEngine(self)
        self.covers = CoverCache(self.lib.dir, self)
        self.covers.changed.connect(self._covers_changed)
        self.hub = StreamHub(self.lib.dir / "stream_spool")
        self.hub.sweep()
        self._theme_sig = None
        self._theme_t = 0.0
        self.engine.tick.connect(self._theme_follow)
        self.analyzer = TrackAnalyzer(self)
        self.analyzer.started.connect(self._on_analysis_started)
        self.analyzer.ready.connect(self._on_analysis_ready)
        self.analyzer.failed.connect(self._on_analysis_failed)

        self.jobs = OnlineJobs(self)
        self.jobs.searchDone.connect(self._on_search_done)
        self.jobs.searchFailed.connect(self._on_search_failed)
        self.jobs.relatedDone.connect(self._on_related_done)
        self.jobs.resolved.connect(self._on_stream_resolved)
        self.jobs.resolveFailed.connect(self._on_stream_failed)
        self.jobs.progress.connect(self._on_dl_progress)
        self.jobs.finished.connect(self._on_dl_finished)
        self.jobs.failed.connect(self._on_dl_failed)
        self.jobs.cancelled.connect(self._on_dl_cancelled)
        self.jobs.cacheDone.connect(self._on_cache_done)
        self.jobs.prefetched.connect(self._on_prefetched)
        self.jobs.networkChecked.connect(self._on_network_checked)
        self.jobs.warmup()
        self.jobs.cacheFailed.connect(self._on_cache_failed)
        self.remote_images = RemoteImages(self)
        self.remote_images.changed.connect(self._remote_images_changed)
        self.presence = DiscordPresence()
        self.ytdlpUpdated.connect(self._on_ytdlp_updated)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(260)
        self.search_timer.timeout.connect(self._live_search)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._flush)

        # theme must be set before widgets paint
        s = self.lib.settings
        T.set_mode(s["mode"])
        T.set_accent(s["accent"], snap=True)

        online.COOKIE_BROWSER[0] = s.get("cookie_browser", "")
        self.presence.configure(s["discord_enabled"], s["discord_app_id"])
        self.build_ui()
        QApplication.instance().setStyleSheet(build_qss())
        self.apply_all_settings()
        self.volume.setValue(int(s["volume"]))
        self.set_volume(int(s["volume"]), save=False)

        self._suggest = self.lib.suggestions(12)
        self.refresh_all()
        self.apply_eq_for("")

        self.meta_timer = QTimer(self)
        self.meta_timer.timeout.connect(self._scan_meta_batch)
        self._queue_meta_scan()
        self.startTimer(250)

        for seq, fn in (("Ctrl+Right", self.next_track), ("Ctrl+Left", self.previous_track),
                        ("Ctrl+Up", lambda: self.nudge_volume(self.lib.settings["volume_step"])),
                        ("Ctrl+Down", lambda: self.nudge_volume(-self.lib.settings["volume_step"])),
                        ("Alt+Right", lambda: self.seek_by(self.lib.settings["seek_step"])),
                        ("Alt+Left", lambda: self.seek_by(-self.lib.settings["seek_step"])),
                        ("Ctrl+E", self.open_equalizer), ("Ctrl+O", self.add_files),
                        ("Ctrl+,", self.open_settings), ("Space", self._space)):
            QShortcut(QKeySequence(seq), self, activated=fn)

        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._sleep_fire)
        self.sleep_minutes = 0
        QTimer.singleShot(0, self._restore_last)
        QTimer.singleShot(0, self._open_start_page)

    # -- helpers shared with delegates / dialogs ------------------------------------------
    def thumb_for(self, path):
        if is_online(path):
            item = self.online_items.get(path)
            return self.remote_images.get(item["thumb_url"], 120) if item else None
        return self.covers.get(path)

    def toast_msg(self, text, ms=2400):
        if self.lib.settings.get("toasts", True) or ms >= 4000:       # errors (long toasts) always show
            self.toast.show_message(text, ms)

    def seek_by(self, seconds):
        if not self.current_path or not self.engine.duration_ms:
            return
        pos = self.engine.position_ms() + int(seconds * 1000)
        self.seek_to_position(max(0, min(int(self.engine.duration_ms) - 500, pos)))

    def set_sleep_timer(self, minutes):
        self._sleep_timer.stop()
        self.sleep_minutes = int(minutes)
        if minutes > 0:
            self._sleep_timer.start(int(minutes) * 60000)
            self.toast_msg(f"Music will pause in {int(minutes)} minutes")
        else:
            self.toast_msg("Sleep timer off")

    def _sleep_fire(self):
        self.sleep_minutes = 0
        if self.engine.playing:
            self.toggle_play()
        self.toast_msg("Sleep timer: music paused. Good night!", 4200)

    def _open_start_page(self):
        if self.lib.settings.get("start_page") == "online":
            self.show_online()

    def _set_title(self, text=""):
        if text and self.lib.settings.get("title_song", True):
            self.setWindowTitle(f"{text} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def save_soon(self):
        self.save_timer.start(1200)

    def _flush(self):
        self.lib.save()

    def _space(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit):
            w.insert(" ")
        else:
            self.toggle_play()

    # -- UI construction ---------------------------------------------------------------
    def build_ui(self):
        central = AuroraBackground(self.engine)
        central.setObjectName("central")
        self.backdrop = central
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._build_sidebar())
        row.addWidget(self._build_main(), 1)
        row.addWidget(self._build_now_playing())
        outer.addLayout(row, 1)
        outer.addWidget(self._build_dock())
        self.toast = Toast(central)

        self.setWindowOpacity(0.0)
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade_animation.setDuration(520)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_animation.start()

    def _build_sidebar(self):
        side = GlassPanel(28)
        side.setFixedWidth(252)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(18, 22, 18, 16)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        brand.setContentsMargins(0, 0, 0, 0)
        brand.addWidget(LogoMark(self.engine, 64))
        brand.addWidget(WordMark(46), 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(20)

        lay.addWidget(eyebrow("DISCOVER"))
        lay.addSpacing(2)
        self.nav_buttons = {}
        for key, label, icon, fn in (
                ("home", "Home", "home", self.show_home),
                ("online", "Online", "globe", self.show_online),
                (ALL, "All tracks", "library", lambda: self.show_collection(ALL)),
                (LIKED, "Liked songs", "heart", lambda: self.show_collection(LIKED)),
                (RECENT, "Recently played", "history", lambda: self.show_collection(RECENT))):
            b = GButton(label, icon, "nav", 19)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(fn)
            lay.addWidget(b)
            self.nav_buttons[key] = b
        lay.addSpacing(14)

        head = QHBoxLayout()
        head.addWidget(eyebrow("PLAYLISTS"))
        head.addStretch(1)
        add_pl = GButton("", "plus", "flat", 15)
        add_pl.setFixedSize(30, 30)
        add_pl.setToolTip("Create a new playlist")
        add_pl.clicked.connect(lambda: self.create_playlist())
        head.addWidget(add_pl)
        lay.addLayout(head)

        self.playlist_list = QListWidget()
        self.playlist_list.setItemDelegate(PlaylistDelegate(self, self.playlist_list))
        self.playlist_list.setMouseTracking(True)
        self.playlist_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.playlist_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self.playlist_context_menu)
        self.playlist_list.itemClicked.connect(self._playlist_clicked)
        lay.addWidget(self.playlist_list, 1)

        self.playlist_hint = QLabel("No playlists yet.\nPress + to create one.")
        self.playlist_hint.setObjectName("muted")
        self.playlist_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.playlist_hint)

        self.stats = QLabel("")
        self.stats.setObjectName("muted")
        self.stats.setWordWrap(True)
        lay.addWidget(self.stats)
        settings = GButton("Settings", "settings", "nav", 19)
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        settings.clicked.connect(lambda: self.open_settings())
        lay.addWidget(settings)
        return side

    def _build_main(self):
        content = GlassPanel(28, 0.30)
        main = QVBoxLayout(content)
        main.setContentsMargins(26, 22, 26, 18)
        main.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search songs, artists, albums…")
        self.search.setClearButtonEnabled(True)
        self._search_action = self.search.addAction(qicon("search", ink(0.60), 18), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._search_submit)
        top.addWidget(self.search, 1)
        add_file = GButton("Add files", "plus", "primary", 17)
        add_file.clicked.connect(self.add_files)
        top.addWidget(add_file)
        add_folder = GButton("Add folder", "folder-plus", "glass", 17)
        add_folder.clicked.connect(self.add_folder)
        top.addWidget(add_folder)
        main.addLayout(top)

        self.pages = QStackedWidget()
        self.home = HomePage(self)
        self.home.playMix.connect(self.play_mix)
        self.home.shuffleAll.connect(self.shuffle_all)
        self.home.refreshSuggestions.connect(self.refresh_suggestions)
        self.home.playPath.connect(self._play_from_home)
        self.home.menuRequested.connect(self.song_menu)
        self.pages.addWidget(self.home)
        self.pages.addWidget(self._build_collection_page())
        self.online = OnlinePage(self)
        self.online.playRequested.connect(self.play_online_key)
        self.online.downloadRequested.connect(self.request_download)
        self.online.menuRequested.connect(self.song_menu)
        self.pages.addWidget(self.online)
        main.addWidget(self.pages, 1)
        return content

    def _build_collection_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.collection_title = QLabel("All tracks")
        self.collection_title.setObjectName("sectionTitle")
        self.collection_count = QLabel("0 tracks")
        self.collection_count.setObjectName("muted")
        tv.addWidget(self.collection_title)
        tv.addWidget(self.collection_count)
        head.addLayout(tv, 1)
        self.col_play = GButton("Play", "play", "primary", 16)
        self.col_play.clicked.connect(self.play_collection)
        self.col_shuffle = GButton("Shuffle", "shuffle", "glass", 16)
        self.col_shuffle.clicked.connect(self.shuffle_collection)
        head.addWidget(self.col_play)
        head.addWidget(self.col_shuffle)
        lay.addLayout(head)

        strip = GlassPanel(20, 0.16)
        strip.setFixedHeight(76)
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        self.col_wave = WaveField(self.engine)
        sl.addWidget(self.col_wave)
        lay.addWidget(strip)

        self.col_header = ColumnHeader()
        lay.addWidget(self.col_header)
        self.tracklist = TrackList(self)
        self.tracklist.playRequested.connect(self._play_from_list)
        self.tracklist.likeRequested.connect(self.toggle_like_path)
        self.tracklist.menuRequested.connect(self.song_menu)
        self.tracklist.orderChanged.connect(self._order_changed)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(10)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel("Your library is empty")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc = QLabel("")
        self.empty_desc.setObjectName("muted")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setWordWrap(True)
        self.empty_btn = GButton("Add music", "plus", "primary", 17)
        self.empty_btn.clicked.connect(self.add_files)
        el.addWidget(self.empty_icon)
        el.addWidget(self.empty_title)
        el.addWidget(self.empty_desc)
        el.addSpacing(8)
        el.addWidget(self.empty_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.tracklist)
        self.list_stack.addWidget(self.empty)
        lay.addWidget(self.list_stack, 1)
        self._refresh_empty_icon()
        return page

    def _refresh_empty_icon(self):
        self.empty_icon.setPixmap(qicon("disc", ink(0.45), 64).pixmap(64, 64))

    def _build_now_playing(self):
        right = GlassPanel(28)
        right.setFixedWidth(344)
        r = QVBoxLayout(right)
        r.setContentsMargins(20, 20, 20, 18)
        r.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(eyebrow("NOW PLAYING"))
        head.addStretch(1)
        self.like_btn = GButton("", "heart", "flat", 20)
        self.like_btn.setFixedSize(36, 36)
        self.like_btn.setToolTip("Favorite this song")
        self.like_btn.clicked.connect(self.toggle_like_current)
        head.addWidget(self.like_btn)
        self.more_btn = GButton("", "more", "flat", 20)
        self.more_btn.setFixedSize(36, 36)
        self.more_btn.setToolTip("More options")
        self.more_btn.clicked.connect(self._more_current)
        head.addWidget(self.more_btn)
        r.addLayout(head)

        self.turntable = Turntable(self.engine)
        r.addWidget(self.turntable, 1)

        self.now_title = ElidedLabel("Nothing playing")
        self.now_title.setObjectName("nowTitle")
        self.now_sub = ElidedLabel("Add local music to get started.")
        self.now_sub.setObjectName("nowSub")
        r.addWidget(self.now_title)
        r.addWidget(self.now_sub)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.fmt_pill = QLabel("")
        self.fmt_pill.setObjectName("pill")
        self.fmt_pill.hide()
        self.analysis_pill = QLabel("")
        self.analysis_pill.setObjectName("pill")
        self.analysis_pill.hide()
        pills.addWidget(self.fmt_pill)
        pills.addWidget(self.analysis_pill)
        pills.addStretch(1)
        r.addLayout(pills)

        self.spectrum = Spectrum(self.engine, 30)
        self.spectrum.setFixedHeight(66)
        r.addWidget(self.spectrum)

        self.eq_btn = GButton("Equalizer", "eq", "glass", 18)
        self.eq_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.eq_btn.clicked.connect(lambda: self.open_equalizer())
        r.addWidget(self.eq_btn)

        r.addWidget(eyebrow("UP NEXT"))
        self.queue = QueueList(self)
        self.queue.setMouseTracking(True)
        self.queue.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.queue.setMinimumHeight(0)
        self.queue.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.queue.itemDoubleClicked.connect(self._play_queue_item)
        r.addWidget(self.queue, 1)
        return right

    def _build_dock(self):
        dock = GlassPanel(30, 0.42)
        dock.setFixedHeight(132)
        d = QHBoxLayout(dock)
        d.setContentsMargins(22, 10, 24, 10)
        d.setSpacing(18)

        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(14)
        self.mini_disc = MiniDisc(self.engine, 78)
        ll.addWidget(self.mini_disc)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addStretch(1)
        self.dock_title = ElidedLabel("Choose a song")
        self.dock_title.setObjectName("dockTitle")
        self.dock_subtitle = ElidedLabel(APP_NAME)
        self.dock_subtitle.setObjectName("muted")
        tl.addWidget(self.dock_title)
        tl.addWidget(self.dock_subtitle)
        tl.addStretch(1)
        ll.addLayout(tl, 1)
        d.addWidget(left, 28)

        center = QVBoxLayout()
        center.setSpacing(0)
        controls = QHBoxLayout()
        controls.setSpacing(4)
        controls.addStretch(1)
        self.shuffle_btn = CatButton("toggle", "shuffle", 0.82)
        self.shuffle_btn.setToolTip("Shuffle")
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.prev_btn = CatButton("prev", "prev", 0.82)
        self.prev_btn.setToolTip("Previous  (Ctrl+Left)")
        self.prev_btn.clicked.connect(self.previous_track)
        self.play_btn = CatButton("play", "play", 0.82)
        self.play_btn.setToolTip("Play / pause  (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn = CatButton("next", "next", 0.82)
        self.next_btn.setToolTip("Next  (Ctrl+Right)")
        self.next_btn.clicked.connect(self.next_track)
        self.repeat_btn = CatButton("toggle", "repeat", 0.82)
        self.repeat_btn.setToolTip("Repeat: Off / All / One")
        self.repeat_btn.clicked.connect(self.cycle_repeat)
        for b in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            controls.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addStretch(1)
        center.addLayout(controls)
        timeline = QHBoxLayout()
        timeline.setSpacing(10)
        self.elapsed = QLabel("0:00")
        self.elapsed.setObjectName("time")
        self.elapsed.setFixedWidth(38)
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.seek = SeekBar(self.engine)
        self.seek.seekStarted.connect(lambda: setattr(self, "_seeking", True))
        self.seek.seekFinished.connect(self.seek_to_position)
        self.duration = QLabel("0:00")
        self.duration.setObjectName("time")
        self.duration.setFixedWidth(38)
        timeline.addWidget(self.elapsed)
        timeline.addWidget(self.seek, 1)
        timeline.addWidget(self.duration)
        center.addLayout(timeline)
        d.addLayout(center, 44)

        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        self.mute_btn = GButton("", "volume-2", "flat", 19)
        self.mute_btn.setToolTip("Mute / unmute")
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.volume = GlassSlider(Qt.Orientation.Horizontal, 0, 100)
        self.volume.setFixedWidth(130)
        self.volume.valueChanged.connect(self.set_volume)
        eq_quick = GButton("", "eq", "flat", 19)
        eq_quick.setToolTip("Equalizer  (Ctrl+E)")
        eq_quick.clicked.connect(lambda: self.open_equalizer())
        right.addWidget(self.mute_btn)
        right.addWidget(self.volume)
        right.addWidget(eq_quick)
        rw = QWidget()
        rw.setLayout(right)
        d.addWidget(rw, 28)
        return dock

    # -- navigation --------------------------------------------------------------------
    def _update_nav(self):
        for key, b in self.nav_buttons.items():
            b.set_active((key == "home" and self.page == "home") or (key == "online" and self.page == "online") or
                         (self.page == "collection" and key == self.current_collection))
        self.playlist_list.viewport().update()
        self.search.setPlaceholderText("Search songs, or paste a song link…" if self.page == "online"
                                       else "Search songs, artists, albums…")

    def _clear_search(self):
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)

    def show_home(self):
        self.page = "home"
        self._clear_search()
        self.pages.setCurrentIndex(0)
        self.refresh_home()
        self._update_nav()

    def show_online(self):
        self.page = "online"
        self._clear_search()
        self.pages.setCurrentIndex(2)
        self.search.setFocus()
        self._update_nav()

    def show_collection(self, name):
        self.page = "collection"
        self.current_collection = name
        self._clear_search()
        self.pages.setCurrentIndex(1)
        self.refresh_collection(keep_scroll=False)
        self._update_nav()

    def _search_changed(self, _text):
        if self.page == "online":
            self.search_timer.start()   # live search as you type (debounced)
            return
        if self.page == "home" and self.search.text().strip():
            self.page = "collection"
            self.current_collection = ALL
            self.pages.setCurrentIndex(1)
            self._update_nav()
        self.refresh_collection(keep_scroll=False)

    def _search_submit(self):
        if self.page == "online":
            self.search_timer.stop()
            q = self.search.text().strip()
            if q:
                self.run_online_search(q)

    def _live_search(self):
        if self.page != "online":
            return
        q = self.search.text().strip()
        if len(q) >= 2:
            self.run_online_search(q)
        elif not q:
            self.last_online_query = ""
            self._search_token = None
            self.online_results = []
            self.online.set_busy(False)
            self.online.show_message("idle")

    def _playlist_clicked(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if name in self.lib.playlists:
            self.show_collection(name)

    # -- refreshing ----------------------------------------------------------------------
    def refresh_all(self):
        self.refresh_sidebar()
        self.refresh_home()
        if self.page == "collection":
            self.refresh_collection()
        self.refresh_queue()
        self._update_nav()

    def refresh_sidebar(self):
        self.playlist_list.clear()
        for name in self.lib.playlist_names():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.UserRole + 1, len(self.lib.playlists[name]))
            self.playlist_list.addItem(item)
        self.playlist_hint.setVisible(not self.lib.playlists)
        self.playlist_list.setVisible(bool(self.lib.playlists))
        self.stats.setText(f"{len(self.lib.tracks)} songs · {len(self.lib.liked)} liked")

    def _greeting(self):
        hour = datetime.now().hour
        return ("GOOD MORNING" if 5 <= hour < 12 else "GOOD AFTERNOON" if 12 <= hour < 18
                else "GOOD EVENING" if hour < 23 else "LATE NIGHT")

    def update_hero(self):
        if self.current_path and self.engine.playing:
            self.home.set_hero("NOW PLAYING", self.lib.title(self.current_path), self.lib.artist(self.current_path))
        else:
            n = len(self.lib.tracks)
            if n:
                desc = f"{n} song{'s' if n != 1 else ''} · {len(self.lib.playlists)} playlist{'s' if len(self.lib.playlists) != 1 else ''}"
            else:
                desc = "Add some music to get started."
            self.home.set_hero(self._greeting(), "Stay in your own frequency.", desc)

    def refresh_home(self):
        self.update_hero()
        self.home.recent.set_paths(self.lib.history[:12], "Songs you play will show up here.")
        if not [p for p in self._suggest if p in self.lib.tracks]:
            self._suggest = self.lib.suggestions(12)
        self._suggest = [p for p in self._suggest if p in self.lib.tracks]
        self.home.suggest.set_paths(self._suggest, "Add music and your favourites will be suggested here.")

    def refresh_suggestions(self):
        self._suggest = self.lib.suggestions(12, exclude=[self.current_path] if self.current_path else ())
        self.refresh_home()

    def _collection_title(self, name):
        return COLLECTION_TITLES.get(name, name)

    def _visible_paths(self):
        q = self.search.text().strip().lower()
        paths = self.lib.collection(self.current_collection)
        if not q:
            return paths
        out = []
        for p in paths:
            hay = " ".join([Path(p).stem, self.lib.title(p), self.lib.artist(p), self.lib.album(p)]).lower()
            if q in hay:
                out.append(p)
        return out

    def refresh_collection(self, keep_scroll=True):
        if self.current_collection not in (ALL, LIKED, RECENT) and self.current_collection not in self.lib.playlists:
            self.current_collection = ALL
        name = self.current_collection
        paths = self._visible_paths()
        sb = self.tracklist.verticalScrollBar()
        pos = sb.value() if keep_scroll else 0
        self.tracklist.setUpdatesEnabled(False)
        self.tracklist.clear()
        for p in paths:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.tracklist.addItem(it)
        self.tracklist.setUpdatesEnabled(True)
        sb.setValue(pos)
        searching = bool(self.search.text().strip())
        self.tracklist.set_reorder_enabled(name != RECENT and not searching)
        self.collection_title.setText(self._collection_title(name))
        self._update_count(len(paths))
        self.col_play.setEnabled(bool(paths))
        self.col_shuffle.setEnabled(bool(paths))
        if paths:
            self.list_stack.setCurrentIndex(0)
        else:
            if not self.lib.tracks:
                self.empty_title.setText("Your library is empty")
                self.empty_desc.setText("Drop audio files anywhere in this window, or add them with the buttons above.")
                self.empty_btn.show()
            elif searching:
                self.empty_title.setText("No matches")
                self.empty_desc.setText("Nothing in this collection matches your search.")
                self.empty_btn.hide()
            elif name == LIKED:
                self.empty_title.setText("No favourites yet")
                self.empty_desc.setText("Tap the heart next to a song to keep it here.")
                self.empty_btn.hide()
            elif name == RECENT:
                self.empty_title.setText("Nothing played yet")
                self.empty_desc.setText("The songs you play will appear here.")
                self.empty_btn.hide()
            else:
                self.empty_title.setText("This playlist is empty")
                self.empty_desc.setText("Open the ⋯ menu on any song and choose “Add to playlist”.")
                self.empty_btn.hide()
            self.list_stack.setCurrentIndex(1)
        QTimer.singleShot(0, self._sync_header_inset)

    def _sync_header_inset(self):
        sb = self.tracklist.verticalScrollBar()
        self.col_header.set_inset(sb.width() if sb.isVisible() else 0)

    def _update_count(self, shown):
        text = f"{shown} song{'s' if shown != 1 else ''}"
        if not self.search.text().strip():
            total = sum(self.lib.duration(p) for p in self.lib.collection(self.current_collection))
            if total > 0:
                mins = total // 60000
                text += f" · {mins // 60} h {mins % 60} min" if mins >= 60 else f" · {mins} min"
        self.collection_count.setText(text)

    def refresh_queue(self):
        self.queue.clear()
        for p in self.queue_paths:
            it = QListWidgetItem(self.lib.title(p))
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.queue.addItem(it)
        self._scroll_queue_to_current()

    def _scroll_queue_to_current(self):
        for i in range(self.queue.count()):
            if self.queue.item(i).data(Qt.ItemDataRole.UserRole) == self.current_path:
                self.queue.scrollToItem(self.queue.item(i), QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    def repaint_lists(self):
        self.tracklist.viewport().update()
        self.queue.viewport().update()
        self.home.viewport().update()
        self.online.repaint_rows()
        for row in (self.home.recent, self.home.suggest):
            for c in row._cards:
                c.update()

    def _covers_changed(self):
        self.repaint_lists()

    # -- importing -------------------------------------------------------------------------
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add music", str(Path.home()),
                                                "Audio files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.wma *.opus);;All files (*.*)")
        if files:
            self.add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Import music folder", str(Path.home()))
        if folder:
            self.add_paths(self._scan_folder(folder))

    @staticmethod
    def _scan_folder(folder):
        try:
            return sorted(str(p) for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
        except OSError:
            return []

    def add_paths(self, paths):
        added = self.lib.add_tracks(paths)
        if added:
            self.save_soon()
            self._queue_meta_scan()
            self.refresh_all()
            self.toast_msg(f"Added {len(added)} song{'s' if len(added) != 1 else ''}")
        else:
            self.toast_msg("Nothing new to add" if paths else "No audio files found", 1800)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = []
        for url in e.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            pth = Path(local)
            if pth.is_dir():
                files.extend(self._scan_folder(str(pth)))
            elif pth.suffix.lower() in AUDIO_EXTS:
                files.append(str(pth))
        if files:
            self.add_paths(files)

    # -- metadata scanning ---------------------------------------------------------------------
    def _queue_meta_scan(self):
        todo = [p for p in self.lib.tracks if "dur" not in (self.lib.meta.get(p) or {}) and p not in self._meta_inflight]
        for p in todo:
            self._meta_inflight.add(p)
            self._meta_pool.submit(self._meta_work, p)
        if todo and not self.meta_timer.isActive():
            self.meta_timer.start(80)

    def _meta_work(self, path):
        """Runs on a worker thread: tag reading never blocks the interface."""
        try:
            info = tags.read_meta(path)
        except Exception:
            info = {"title": "", "artist": "", "album": "", "dur": 0, "bitrate": 0}
        self._meta_done.append((path, info))

    def _scan_meta_batch(self):
        n = 0
        while self._meta_done and n < 30:
            path, info = self._meta_done.popleft()
            self._meta_inflight.discard(path)
            if path in self.lib.tracks:
                self.lib.meta.setdefault(path, {}).update(info)
            n += 1
        if n:
            self.repaint_lists()
        if not self._meta_inflight and not self._meta_done:
            self.meta_timer.stop()
            self._update_count(self.tracklist.count())
            self.save_soon()

    # -- playback ----------------------------------------------------------------------------------
    def _set_queue(self, paths, name=None):
        self.queue_paths = list(paths)
        self.queue_name = name
        self.radio_on = False
        self._shuf_done = set()
        self.refresh_queue()

    def _play_from_list(self, path):
        paths = self.tracklist.paths()
        name = self.current_collection if not self.search.text().strip() else None
        self._set_queue(paths, name)
        self.play_any(path)

    def _play_from_home(self, path):
        if path in self._suggest:
            self._set_queue(self._suggest, None)
        else:
            self._set_queue(self.lib.history, None)
        self.play_any(path)

    def _play_queue_item(self, item):
        self.play_any(item.data(Qt.ItemDataRole.UserRole))

    def play_mix(self):
        if not self.lib.tracks:
            self.add_files()
            return
        if not self._suggest:
            self._suggest = self.lib.suggestions(12)
        self._set_queue(self._suggest, None)
        self.play_path(self._suggest[0])

    def shuffle_all(self):
        if not self.lib.tracks:
            self.add_files()
            return
        self.shuffle = True
        self.shuffle_btn.set_active(True)
        self._set_queue(self.lib.tracks, ALL)
        self.play_path(random.choice(self.lib.tracks))

    def play_collection(self):
        paths = self.tracklist.paths()
        if paths:
            self._set_queue(paths, self.current_collection if not self.search.text().strip() else None)
            self.play_any(paths[0])

    def shuffle_collection(self):
        paths = self.tracklist.paths()
        if paths:
            self.shuffle = True
            self.shuffle_btn.set_active(True)
            self._set_queue(paths, self.current_collection if not self.search.text().strip() else None)
            self.play_any(random.choice(paths))

    def play_path(self, path, autoplay=True, start_ms=0, push=True):
        if path not in self.lib.tracks:
            return
        if not Path(path).is_file():
            self.toast_msg("This file is missing – it was moved or deleted.", 3200)
            try:
                self.player.stop()
            except Exception:
                pass
            self.engine.set_playing(False)
            self.play_btn.set_icon("play")
            self._req_t = _time.monotonic()
            return
        if push and self.current_path and self.current_path != path:
            self._play_stack.append(self.current_path)
            del self._play_stack[:-50]
        self.current_path = path
        self.loading_key = ""
        if path not in self.queue_paths:
            self._set_queue(self.lib.tracks, ALL)
        self._req_t = _time.monotonic() if autoplay else 0.0
        self._pending_seek = start_ms if start_ms > 0 else None
        self._listen_acc = 0.0
        self._listen_done = False
        self.player.set_media(self.instance.media_new_path(path))
        if autoplay:
            self.player.play()
        self.player.audio_set_volume(self.volume.value())
        self.apply_eq_for(path)

        meta = self.lib.meta.setdefault(path, {})
        if "dur" not in meta:
            meta.update(tags.read_meta(path))
        self._load_cover(path)
        title, artist = self.lib.title(path), self.lib.artist(path)
        eng = self.engine
        eng.seed = zlib.crc32(path.encode("utf-8", "ignore")) & 0xFFFF
        eng.analysis = None
        eng.duration_ms = meta.get("dur", 0)
        eng.set_position(start_ms)
        eng.set_playing(bool(autoplay))
        self.seek.set_envelope(None)
        self._start_analysis(path)
        self.turntable.set_cover(self.cover_pix)
        self.mini_disc.set_cover(self.cover_pix)
        self._apply_theme_colour()

        self._update_now_labels()
        ext = Path(path).suffix.lstrip(".").upper()
        br = meta.get("bitrate", 0)
        self.fmt_pill.setText(f"{ext} · {br} kbps" if br else ext)
        self.fmt_pill.show()
        self.seek.setRange(0, meta.get("dur", 0))
        self.seek.setValue(start_ms)
        self.elapsed.setText(nice_time(start_ms))
        self.duration.setText(nice_time(meta.get("dur", 0)))
        self.play_btn.set_icon("pause" if autoplay else "play")
        self._set_title(title)
        if autoplay:
            self.lib.record_play(path)
            self.save_soon()
            if self.page == "home":
                self.refresh_home()
            if self.page == "collection" and self.current_collection == RECENT:
                self.refresh_collection()
        self._sync_like_button()
        self.repaint_lists()
        self._scroll_queue_to_current()

    def _update_now_labels(self):
        path = self.current_path
        if not path:
            return
        title, artist = self.lib.title(path), self.lib.artist(path)
        self.now_title.set_full_text(title)
        self.now_sub.set_full_text(artist)
        self.dock_title.set_full_text(title)
        self.dock_subtitle.set_full_text(artist)
        self._set_title(title)

    def _reset_now_labels(self):
        self.now_title.set_full_text("Nothing playing")
        self.now_sub.set_full_text("Add local music to get started.")
        self.dock_title.set_full_text("Choose a song")
        self.dock_subtitle.set_full_text(APP_NAME)
        self.fmt_pill.hide()
        self.analysis_pill.hide()
        self.setWindowTitle(APP_NAME)

    def _load_cover(self, path):
        self.cover_pix = None
        pm = pixmap_from_bytes(tags.read_cover(path))
        if pm is not None:
            self.cover_pix = square_pixmap(pm, 480)
            thumb = square_pixmap(pm, 220)
            if thumb is not None:
                self.covers.set_override(path, thumb)

    def _apply_theme_colour(self):
        s = self.lib.settings
        if s["adaptive"]:
            hue = None
            if self.cover_pix is not None:
                hue = cover_hue(self.cover_pix)
            if hue is None and self.current_path:
                hue = hue_for(self.lib.title(self.current_path) + self.lib.artist(self.current_path))
            if hue is not None:
                T.set_hue_targets(hue)
                return
        T.set_accent(s["accent"])

    # -- analysis ------------------------------------------------------------------------------------
    def _start_analysis(self, path):
        self._analysis_target = path
        if not self.analyzer.available:
            self.analysis_pill.setText("Simulated waves")
            self.analysis_pill.setToolTip("Install numpy and miniaudio so the waves follow the real sound.")
            self.analysis_pill.show()
            return
        self.analysis_pill.setText("Analysing audio…")
        self.analysis_pill.setToolTip("")
        self.analysis_pill.show()
        self.analyzer.start(path)

    def _on_analysis_started(self, path, analysis):
        if path == self._analysis_target:
            self.engine.analysis = analysis

    def _on_analysis_ready(self, path, analysis):
        if path == self._analysis_target:
            self.engine.analysis = analysis
            self.seek.set_envelope(analysis.envelope)
            self.analysis_pill.setText("Live spectrum")
            self.analysis_pill.setToolTip("The waves follow the real sound of this song.")

    def _fallback_cache(self, key):
        """Second way to get real waves for a stream: fetch the audio once, then analyse the file."""
        item = self.online_items.get(key)
        if item and not self._cache_tried and getattr(self, "_stream_url", ""):
            self._cache_tried = True
            self.analysis_pill.setText("Preparing waves…")
            self.analysis_pill.setToolTip("Fetching the audio once so the waves can follow the real sound.")
            self.jobs.cache_audio(item, self._stream_cache_dir(), self._stream_url)
        else:
            self.analysis_pill.setText("Streaming")
            self.analysis_pill.setToolTip("The waves are simulated for this stream.")

    def _on_analysis_failed(self, path):
        if path == self._analysis_target and path == self.current_path and path in self.online_items \
                and not self._cache_tried:
            self._fallback_cache(path)
            return
        if path == self._analysis_target:
            self.analysis_pill.setText("Simulated waves")
            self.analysis_pill.setToolTip("This file could not be analysed, so the waves are simulated.")

    # -- transport -------------------------------------------------------------------------------------
    def _vlc_state(self):
        try:
            return self.player.get_state()
        except Exception:
            return None

    def toggle_play(self):
        if not self.lib.tracks and not self.current_path:
            self.add_files()
            return
        if self.loading_key and self.loading_key == self.current_path:
            return                                   # still connecting to the stream
        state = self._vlc_state()
        if state == vlc.State.Playing:
            self.player.pause()
            self.engine.set_playing(False)
            self._req_t = 0.0
        elif self.current_path:
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                self.play_any(self.current_path, push=False)
            else:
                self.player.play()
                self._req_t = _time.monotonic()
                self.engine.set_playing(True)
        else:
            paths = self.tracklist.paths() if self.page == "collection" else []
            if paths:
                self._set_queue(paths, self.current_collection)
                self.play_any(paths[0])
            else:
                self.play_mix()
        self.play_btn.set_icon("pause" if self.engine.playing else "play")
        self.update_hero()

    def timerEvent(self, _event):
        self.on_timer_tick()

    def on_timer_tick(self):
        if not self.current_path:
            return
        state = self._vlc_state()
        playing = state in (vlc.State.Playing, vlc.State.Opening, vlc.State.Buffering)
        recently = _time.monotonic() - self._req_t < 1.5
        if not playing and recently and state in (vlc.State.NothingSpecial, vlc.State.Stopped):
            playing = True
        if self.loading_key and self.loading_key == self.current_path:
            playing = True                           # connecting to a stream
        length = self.player.get_length()
        tm = self.player.get_time()
        eng = self.engine
        if length > 0:
            if self.seek.value() > length:
                self.seek.setValue(length)
            self.seek.setRange(0, length)
            self.duration.setText(nice_time(length))
            eng.duration_ms = length
            m = self.lib.meta.setdefault(self.current_path, {})
            if not m.get("dur"):
                m["dur"] = length
        if self._pending_seek is not None and state == vlc.State.Playing and length > 0:
            self.player.set_time(int(self._pending_seek))
            eng.set_position(self._pending_seek)
            self._pending_seek = None
        elif tm >= 0 and not self._seeking and self._pending_seek is None:
            self.seek.setValue(tm)
            self.elapsed.setText(nice_time(tm))
            if not is_online(self.current_path):
                self.lib.last_pos = tm
            eng.sync_position(tm)
        eng.set_playing(playing)
        self.play_btn.set_icon("pause" if playing else "play")

        if playing and state == vlc.State.Playing:
            self._listen_acc += 0.25
            if self._listen_acc > 3.0:                  # it really plays: forget earlier hiccups
                self._error_count = 0
                self._retried.discard(self.current_path)
            need = LISTEN_SECONDS
            dur = self.lib.duration(self.current_path)
            if 0 < dur < LISTEN_SECONDS * 2000:
                need = max(3.0, dur / 2000.0)
            if not self._listen_done and self._listen_acc >= need:
                self._listen_done = True
                self.lib.record_listen(self.current_path)
                self.save_soon()
            self._save_ticks += 1
            if self._save_ticks >= 80:   # remember the position every ~20 s
                self._save_ticks = 0
                self.save_soon()

        if state == vlc.State.Error and not self.loading_key and _time.monotonic() - self._req_t > 1.5:
            self._on_playback_error()
        elif state == vlc.State.Ended and _time.monotonic() - self._req_t > 1.5:
            dur_known = self.lib.duration(self.current_path) or 0
            if is_online(self.current_path) and not self.loading_key and dur_known > 0 and 0 <= tm < dur_known - 6000:
                self._on_playback_error()              # the stream stopped early (connection) - not a real end
                return
            eng.set_playing(False)
            self._error_count = 0
            self.advance_track(auto=True)
        if state == vlc.State.Buffering and is_online(self.current_path) and not self.loading_key:
            now = _time.monotonic()
            if not self._buf_t:
                self._buf_t = now
            elif now - self._buf_t > 20:               # stuck buffering: the connection is gone or very bad
                self._buf_t = 0.0
                self._on_playback_error()
                return
        else:
            self._buf_t = 0.0
        sig = (self.current_path, bool(playing and state != vlc.State.Buffering), length // 2000)
        if sig != self._presence_sig:
            self._presence_sig = sig
            self.sync_presence()
        hs = (self.current_path, eng.playing)
        if hs != self._hero_state:
            self._hero_state = hs
            self.update_hero()
            self.repaint_lists()

    def _on_playback_error(self):
        """A stream died (expired link, lost connection): reconnect and carry on from the same second; if the
        internet is gone wait for it; only skip a song that really cannot be played."""
        cur = self.current_path
        self._req_t = _time.monotonic()
        if is_online(cur):
            try:
                pos = max(0, int(self.player.get_time()))
            except Exception:
                pos = 0
            if cur not in self._retried:
                self._retried.add(cur)
                self.toast_msg("Connection lost - reconnecting…", 2000)
                online.forget(cur)
                self.play_stream(cur, push=False, start_ms=pos)
                return
            cycles = self._net_cycles.get(cur, 0)
            if cycles < 2:                             # second failure: probably no internet - wait for it
                self._net_cycles[cur] = cycles + 1
                online.forget(cur, bad=True)
                self._wait_for_network(cur, pos)
                return
            self._net_cycles.pop(cur, None)
        self._retried.discard(cur)
        self._error_count += 1
        self.engine.set_playing(False)
        if self._error_count >= 3:
            self.player.stop()
            self.toast_msg("Playback keeps failing. Check your internet connection.", 4200)
            self.play_btn.set_icon("play")
            return
        self.toast_msg("This song can't be played - skipping.", 2200)
        self.advance_track(auto=True)

    # -- no internet: wait, then continue by itself ----------------------------------------------------------
    def _wait_for_network(self, key, pos=0):
        self._net_wait_key = key
        self._net_wait_pos = int(pos)
        self._net_ticks = 0
        self.loading_key = ""
        try:
            self.player.stop()
        except Exception:
            pass
        self.engine.set_playing(False)
        self.play_btn.set_icon("play")
        self.analysis_pill.setText("Waiting for internet…")
        self.analysis_pill.show()
        self.toast_msg("No internet - NILKON will continue as soon as it is back.", 3600)
        self._start_net_timer()

    def _start_net_timer(self):
        if not self._net_timer.isActive():
            self._net_timer.start(2500)
        self.jobs.check_network()

    def _on_network_checked(self, ok):
        if not (self._net_wait_key or self._search_wait):
            self._net_timer.stop()
            return
        if not ok:
            self._net_ticks += 1
            if self._net_ticks > 120:                  # ~5 minutes: stop waiting
                self._net_timer.stop()
                self._net_wait_key = ""
                self._search_wait = False
                self.toast_msg("Still no internet. Press play again when you are back online.", 4200)
            return
        self._net_timer.stop()
        self._net_ticks = 0
        self.remote_images.reset_failed()
        if self._search_wait:
            self._search_wait = False
            self.retry_online_search()
        key, self._net_wait_key = self._net_wait_key, ""
        if key and key == self.current_path and not self.engine.playing:
            self.toast_msg("Back online", 1600)
            self._retried.discard(key)
            self.play_stream(key, push=False, start_ms=self._net_wait_pos)

    def seek_to_position(self, value):
        self._pending_seek = None
        self.player.set_time(int(value))
        self.engine.set_position(value)
        self.elapsed.setText(nice_time(value))
        if not is_online(self.current_path):
            self.lib.last_pos = int(value)
        self._seeking = False
        self.sync_presence()

    def _queue_for_nav(self):
        q = [p for p in self.queue_paths if p in self.lib.tracks or p in self.online_items]
        return q or list(self.lib.tracks)

    def _playable(self, p):
        return p in self.online_items or is_online(p) or (p in self.lib.tracks and Path(p).is_file())

    def advance_track(self, auto=False):
        paths = self._queue_for_nav()
        if not paths:
            return
        if auto and self.repeat == "One" and self._playable(self.current_path):
            self.play_any(self.current_path, push=False)
            return
        cur = self.current_path
        nxt = None
        for _ in range(len(paths) + 1):                # skip songs whose file went missing
            cand = self._pick_next(paths, cur, auto)
            if cand is None:
                return                                 # end of the queue (handled inside)
            if self._playable(cand):
                nxt = cand
                break
            cur = cand
            self._shuf_done.add(cand)
        if nxt is None:
            self.toast_msg("None of the next songs can be found.", 3200)
            self.player.stop()
            self.engine.set_playing(False)
            self.play_btn.set_icon("play")
            return
        self.play_any(nxt)

    def _pick_next(self, paths, cur, auto):
        if self.shuffle and len(paths) > 1:
            return self._next_shuffled(paths, cur)
        try:
            idx = paths.index(cur)
        except ValueError:
            idx = -1
        if idx + 1 < len(paths):
            return paths[idx + 1]
        # end of the queue
        key = self._canon(self.current_path)
        if self.radio_on and key in self.online_items:
            if auto and self.repeat != "All":
                self._radio_wait = True                 # similar songs are being fetched: continue when they arrive
                self.analysis_pill.setText("Finding similar songs…")
                self._request_related(self.online_items[key], force=True)
                QTimer.singleShot(9000, self._radio_wait_timeout)
                return None
            if not self._radio_busy:
                self._request_related(self.online_items[key], force=True)
        if self.repeat == "All" or not auto:
            return paths[0]
        self._stop_at_end()
        return None

    def _stop_at_end(self):
        self.player.stop()
        self.engine.set_playing(False)
        self.engine.set_position(0)
        self.seek.setValue(0)
        self.elapsed.setText("0:00")
        self.play_btn.set_icon("play")
        self._req_t = 0.0

    def _radio_wait_timeout(self):
        if self._radio_wait:
            self._radio_wait = False
            self._stop_at_end()

    def _canon(self, path):
        """The online key of a downloaded copy (so favourites / radio treat both as one song)."""
        if not path or is_online(path):
            return path
        for k, v in self.lib.downloads.items():
            if v == path:
                return k
        return path

    def next_track(self):
        self.advance_track(auto=False)

    def previous_track(self):
        if not self.current_path:
            return
        if self.player.get_time() > 3000:
            self.player.set_time(0)
            self.engine.set_position(0)
            return
        while self._play_stack:
            prev = self._play_stack.pop()
            if prev in self.online_items or (prev in self.lib.tracks and Path(prev).is_file()):
                self.play_any(prev, push=False)
                return
        paths = self._queue_for_nav()
        try:
            idx = paths.index(self.current_path)
        except ValueError:
            idx = 0
        self.play_any(paths[(idx - 1) % len(paths)], push=False)

    def _next_shuffled(self, paths, cur=None):
        """Random order without repeats: every song plays once before any song plays again."""
        cur = cur or self.current_path
        self._shuf_done.add(cur)
        pool = [p for p in paths if p not in self._shuf_done]
        if not pool:                                    # the round is over -> start a fresh one
            self._shuf_done = {cur}
            pool = [p for p in paths if p != cur]
            recent = set(self._play_stack[-3:])
            fresh = [p for p in pool if p not in recent]
            pool = fresh or pool
        return random.choice(pool)

    def toggle_shuffle(self):
        self._shuf_done = set()
        self.shuffle = not self.shuffle
        self.shuffle_btn.set_active(self.shuffle)
        self.toast_msg(f"Shuffle {'on' if self.shuffle else 'off'}", 1600)

    def cycle_repeat(self):
        modes = ["Off", "All", "One"]
        self.repeat = modes[(modes.index(self.repeat) + 1) % len(modes)]
        self.repeat_btn.set_icon("repeat-1" if self.repeat == "One" else "repeat")
        self.repeat_btn.set_active(self.repeat != "Off")
        self.toast_msg(f"Repeat: {self.repeat}", 1600)

    def set_volume(self, value, save=True):
        value = int(value)
        self.player.audio_set_volume(value)
        self.lib.settings["volume"] = value
        self._update_volume_icon()
        if save:
            self.save_soon()

    def nudge_volume(self, delta):
        v = max(0, min(100, self.volume.value() + delta))
        self.volume.setValue(v)
        self.set_volume(v)

    def toggle_mute(self):
        if self.volume.value() > 0:
            self._pre_mute = self.volume.value()
            self.volume.setValue(0)
        else:
            self.volume.setValue(self._pre_mute or 75)
        self.set_volume(self.volume.value())

    def _update_volume_icon(self):
        v = self.volume.value()
        self.mute_btn.set_icon("volume-x" if v == 0 else "volume-1" if v < 50 else "volume-2")

    def _restore_last(self):
        p = self.lib.last_path
        if self.lib.settings.get("resume_last", True) and p and p in self.lib.tracks and Path(p).is_file():
            self._set_queue(self.lib.tracks, ALL)
            self.play_path(p, autoplay=False, start_ms=max(0, int(self.lib.last_pos)))

    # -- favourites ---------------------------------------------------------------------------------
    def _sync_like_button(self):
        liked = bool(self.current_path) and self.lib.is_liked(self._canon(self.current_path))
        self.like_btn.set_icon("heart-fill" if liked else "heart")
        self.like_btn.set_active(liked)

    def toggle_like_path(self, path):
        if is_online(path):
            item = self.online_items.get(path)
            if item:
                self.lib.register_online(item)
        now = self.lib.toggle_like(path)
        self.save_soon()
        self._sync_like_button()
        self.stats.setText(f"{len(self.lib.tracks)} songs · {len(self.lib.liked)} liked")
        if self.page == "collection" and self.current_collection == LIKED:
            self.refresh_collection()
        else:
            self.repaint_lists()
        self.toast_msg("Added to Liked songs" if now else "Removed from Liked songs", 1600)

    def toggle_like_current(self):
        if self.current_path:
            self.toggle_like_path(self._canon(self.current_path))

    def _more_current(self):
        if self.current_path:
            self.song_menu(self.current_path, self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    # -- online: search -------------------------------------------------------------------------
    def run_online_search(self, query):
        query = (query or "").strip()
        if not query:
            return
        key = query.lower()
        self.last_online_query = query
        cached = self._search_cache.get(key)
        if cached is not None:
            self._search_cache.move_to_end(key)
            self._search_token = None                 # a slower search still in flight must not replace these
            self._show_results(cached)
            return
        self.online.set_busy(True)
        if not self.online_results:
            self.online.show_message("loading")
        self._search_token = self.jobs.search(query)
        self._search_query = query

    def retry_online_search(self):
        if self.last_online_query:
            self._search_cache.pop(self.last_online_query.lower(), None)
            self.run_online_search(self.last_online_query)

    def _show_results(self, items):
        self.online.set_busy(False)
        self.online_results = list(items)
        for it in items:
            self.online_items.setdefault(it["key"], it)
            self.lib.see_online(it)
        self._prune_online_items()
        if items:
            self.online.set_results(items)
        else:
            self.online.show_message("empty")

    def _on_search_done(self, token, items):
        if token != self._search_token:
            return
        self._search_cache[(getattr(self, "_search_query", "") or self.last_online_query).lower()] = list(items)
        for it in list(items)[:2]:                     # look up the first songs' stream addresses now: Play starts at once
            self.jobs.prefetch(it)
        while len(self._search_cache) > 40:
            self._search_cache.popitem(last=False)
        self._show_results(items)

    def _on_search_failed(self, token, msg):
        if token != self._search_token:
            return
        self.online.set_busy(False)
        if str(msg).startswith("No internet"):
            self._search_wait = True                   # search again by itself when the connection is back
            self._start_net_timer()
        if self.online_results:
            self.toast_msg(msg, 3200)
        else:
            self.online.show_message("error", msg)

    def _prune_online_items(self):
        if len(self.online_items) <= 600:
            return
        keep = (set(self.queue_paths) | {self.current_path} | set(self.lib.downloads) | set(self.lib.online_meta)
                | {i["key"] for i in self.online_results})
        for k in [k for k in self.online_items if k not in keep]:
            del self.online_items[k]

    def _remote_images_changed(self):
        cur = self.current_path
        if cur and is_online(cur) and self.cover_pix is None:
            item = self.online_items.get(cur)
            pm = self.remote_images.get(item["cover_url"], 480) if item else None
            if pm is not None:
                self.cover_pix = pm
                self.turntable.set_cover(pm)
                self.mini_disc.set_cover(pm)
                self._apply_theme_colour()
        self.repaint_lists()

    # -- online: playback -----------------------------------------------------------------------
    def is_cur(self, path):
        cur = self.current_path
        return bool(cur) and (path == cur or (is_online(path) and self.lib.downloads.get(path) == cur))

    def play_any(self, path, push=True):
        self._shuf_done.add(path)
        if not is_online(path):
            self.play_path(path, push=push)
            return
        loc = self._local_copy(path)
        if loc:                                   # a downloaded song plays from disk, even offline
            if path in self.queue_paths and loc not in self.queue_paths:
                self.queue_paths[self.queue_paths.index(path)] = loc
                self.refresh_queue()
            self.play_path(loc, push=push)
        else:
            self.play_stream(path, push=push)

    def _local_copy(self, key):
        loc = self.lib.downloads.get(key)
        if loc and loc in self.lib.tracks and Path(loc).is_file():
            return loc
        return None

    def play_online_key(self, key):
        item = self.online_items.get(key)
        if not item:
            return
        target = self._local_copy(key) or key
        if target == self.current_path:
            self.toggle_play()
            return
        self._set_queue([key], None)               # the song, then an automatic queue of related songs
        self.radio_on = bool(self.lib.settings.get("auto_radio", True))
        self.radio_seed = key
        self._radio_busy = False
        self.play_any(key)
        self._request_related(item)

    def _request_related(self, item, force=False):
        if self._radio_busy and not force:
            return
        self._radio_busy = True
        self.jobs.related(item)

    def _on_related_done(self, seed, items):
        if seed != self.radio_seed and seed not in self.queue_paths and seed != self._canon(self.current_path) \
                and self.lib.downloads.get(seed) not in self.queue_paths:
            return                                    # belongs to a radio that is no longer active
        self._radio_busy = False
        waiting = self._radio_wait
        if not self.radio_on or not items:
            if waiting:
                self._radio_wait = False
                self._stop_at_end()
            return
        have = set(self.queue_paths) | set(self.lib.downloads.get(k, "") for k in self.queue_paths if is_online(k))
        added = []
        for it in items:
            k = it["key"]
            if k in have or self.lib.downloads.get(k) in have:
                continue
            self.online_items.setdefault(k, it)
            self.lib.see_online(it)
            added.append(self._local_copy(k) or k)
            have.add(k)
        if not added:
            if waiting:
                self._radio_wait = False
                self._stop_at_end()
            return
        self.queue_paths.extend(added[:60])
        del self.queue_paths[:-300]
        self.refresh_queue()
        self._prefetch_next()
        if waiting:
            self._radio_wait = False
            self.advance_track(auto=True)

    def _maybe_extend_radio(self):
        if not self.radio_on or self._radio_busy or not self.current_path:
            return
        try:
            idx = self.queue_paths.index(self.current_path)
        except ValueError:
            return
        if len(self.queue_paths) - idx <= 3:
            seed = self.queue_paths[-1]
            item = self.online_items.get(seed) or self.online_items.get(self.current_path)
            if item:
                self._request_related(item)

    def _prefetch_next(self):
        """Resolve the next streamed song in advance so it starts without waiting."""
        try:
            idx = self.queue_paths.index(self.current_path)
        except ValueError:
            return
        for p in self.queue_paths[idx + 1: idx + 3]:
            item = self.online_items.get(p) if is_online(p) else None
            if item:
                self.jobs.prefetch(item)

    def play_stream(self, key, push=True, start_ms=0):
        item = self.online_items.get(key)
        if not item:
            return
        if push and self.current_path and self.current_path != key:
            self._play_stack.append(self.current_path)
            del self._play_stack[:-50]
        self.current_path = key
        if key not in self.queue_paths:
            self._set_queue([key], None)
        self._req_t = 0.0
        self._pending_seek = int(start_ms) if start_ms and start_ms > 1500 else None
        self._listen_acc = 0.0
        self.loading_key = key
        self.analyzer.cancel()
        self._analysis_target = ""
        try:
            self.player.stop()
        except Exception:
            pass
        self.lib.register_online(item)
        meta = self.lib.meta.setdefault(key, {})
        meta.update(title=item["title"], artist=item["artist"] or "Unknown artist", album="Online",
                    dur=int(item.get("duration_ms") or 0), bitrate=0)
        self._listen_done = False
        self.cover_pix = self.remote_images.get(item["cover_url"], 480)
        eng = self.engine
        eng.seed = zlib.crc32(key.encode("utf-8", "ignore")) & 0xFFFF
        eng.analysis = None
        eng.duration_ms = meta["dur"]
        eng.set_position(0)
        eng.set_playing(True)
        self.seek.set_envelope(None)
        self.turntable.set_cover(self.cover_pix)
        self.mini_disc.set_cover(self.cover_pix)
        self._apply_theme_colour()
        self._update_now_labels()
        self.analysis_pill.setText("Connecting…")
        self.analysis_pill.setToolTip("")
        self.analysis_pill.show()
        self.fmt_pill.setText("ONLINE · stream")
        self.fmt_pill.show()
        self.seek.setRange(0, meta["dur"])
        self.seek.setValue(0)
        self.elapsed.setText("0:00")
        self.duration.setText(nice_time(meta["dur"]))
        self.play_btn.set_icon("pause")
        self._set_title(meta['title'])
        self._sync_like_button()
        self.repaint_lists()
        self._scroll_queue_to_current()
        self.lib.record_play(key)
        self.save_soon()
        if self.page == "home":
            self.refresh_home()
        elif self.page == "collection" and self.current_collection == RECENT:
            self.refresh_collection()
        self.jobs.resolve(item)
        self._maybe_extend_radio()
        self.sync_presence()

    def _on_stream_resolved(self, key, url, dur):
        if key != self.current_path or key != self.loading_key:
            return
        self.loading_key = ""
        play_url = url
        try:                                           # one buffered download shared by the player and the waves
            item0 = self.online_items.get(key)
            play_url = self.hub.start(key, url, refresh=(lambda it=item0: self._fresh_url(it)) if item0 else None)
        except Exception:
            play_url = url
        local_proxy = play_url != url
        try:
            media = self.instance.media_new(play_url)
            media.add_option(":network-caching=%d" % (400 if local_proxy else 2500))
            self.player.set_media(media)
            self.player.play()
            self.player.audio_set_volume(self.volume.value())
        except Exception as exc:
            self.loading_key = key
            self._on_stream_failed(key, f"Could not start playback: {exc}")
            return
        self.apply_eq_for(key)
        self._req_t = _time.monotonic()
        meta = self.lib.meta.setdefault(key, {})
        if dur > 0:
            meta["dur"] = int(dur)
            self.engine.duration_ms = int(dur)
            self.seek.setRange(0, int(dur))
            self.duration.setText(nice_time(int(dur)))
        self.engine.set_playing(True)
        item = self.online_items.get(key)
        self._stream_url = url
        self._cache_tried = False
        self.analyzer.expected_seconds = (dur / 1000.0) if dur > 0 else 0.0
        if item and self.analyzer.available:
            # live analysis straight from the stream: the waves start within a second of the song
            self._analysis_target = key
            self.engine.analysis = None
            self.analysis_pill.setText("Starting waves…")
            self.analysis_pill.setToolTip("")
            if not self.analyzer.start_stream(key, play_url):
                self._fallback_cache(key)
        else:
            self.analysis_pill.setText("Streaming")
        self.repaint_lists()
        self.update_hero()
        self._prefetch_next()
        self.sync_presence()

    def _on_stream_failed(self, key, msg):
        if key != self.current_path or key != self.loading_key:
            return
        if str(msg).startswith("No internet"):
            self._wait_for_network(key, self._pending_seek or 0)
            return
        self.loading_key = ""
        self.engine.set_playing(False)
        self.play_btn.set_icon("play")
        self.analysis_pill.setText("Couldn't load")
        self.toast_msg(msg, 4200)
        self.repaint_lists()
        self.sync_presence()
        self._error_count += 1
        if self._error_count < 3 and self.radio_on or (self._error_count < 3 and len(self.queue_paths) > 1):
            QTimer.singleShot(900, lambda k=key: self.advance_track(auto=True) if self.current_path == k else None)

    def _on_prefetched(self, key, url):
        """The next song's address is known: start fetching its first seconds so it begins instantly."""
        try:
            idx = self.queue_paths.index(self.current_path)
        except ValueError:
            return
        if key in self.queue_paths[idx + 1: idx + 3] and key != self.current_path:
            item = self.online_items.get(key)
            if item:
                try:
                    self.hub.start(key, url, refresh=lambda it=item: self._fresh_url(it), prefetch=True)
                except Exception:
                    pass

    @staticmethod
    def _fresh_url(item):
        """A new stream address when the old one expired in the middle of a song."""
        online.forget(item["key"], bad=True)
        return online.resolve(item)[0]

    def _stream_cache_dir(self):
        return self.lib.dir / "stream_cache"

    def _on_cache_done(self, key, path):
        if key == self.current_path:
            self._start_analysis(path)
        try:
            files = sorted(self._stream_cache_dir().glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[6:]:
                if str(f) != path:
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def _on_cache_failed(self, key):
        if key == self.current_path:
            self.analysis_pill.setText("Streaming")
            self.analysis_pill.setToolTip("The waves are simulated for this stream.")

    # -- online: downloads ----------------------------------------------------------------------
    def download_state(self, key):
        st = self.dl_states.get(key)
        if st:
            return st
        if self._local_copy(key):
            return {"state": "done", "pct": 1.0}
        return {"state": "idle", "pct": 0.0}

    def _dl_changed(self):
        self.online.repaint_rows()

    def request_download(self, key):
        item = self.online_items.get(key)
        if not item:
            return
        st = self.download_state(key)["state"]
        if st in ("queued", "downloading"):
            self.jobs.cancel(key)
            return
        if st == "done":
            self.toast_msg("Already in your library.", 1800)
            return
        folder = self.lib.download_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.toast_msg(f"Can't use the download folder: {exc}", 4200)
            return
        self.dl_states[key] = {"state": "queued", "pct": 0.0}
        self._dl_changed()
        self.jobs.download(item, folder, self.lib.settings["download_format"])

    def _on_dl_progress(self, key, frac):
        if key in self.dl_states:
            self.dl_states[key] = {"state": "downloading", "pct": float(frac)}
            self._dl_changed()

    def _on_dl_finished(self, key, path):
        self.dl_states.pop(key, None)
        item = self.online_items.get(key) or {}
        try:
            rp = str(Path(path).resolve())
        except OSError:
            rp = path
        self.lib.add_tracks([rp])
        if rp not in self.lib.tracks:
            self._on_dl_failed(key, "The downloaded file could not be added.")
            return
        meta = self.lib.meta.setdefault(rp, {})
        meta.update(tags.read_meta(rp))
        if not meta.get("title"):
            meta["title"] = item.get("title", "") or Path(rp).stem
        if not meta.get("artist") and item.get("artist"):
            meta["artist"] = item["artist"]
        if not meta.get("dur") and item.get("duration_ms"):
            meta["dur"] = int(item["duration_ms"])
        self.lib.downloads[key] = rp
        self.save_soon()
        self.refresh_all()
        self._dl_changed()
        self.toast_msg(f"Downloaded “{meta.get('title') or Path(rp).stem}”", 2600)

    def _on_dl_failed(self, key, msg):
        self.dl_states[key] = {"state": "error", "pct": 0.0, "error": msg}
        self._dl_changed()
        self.toast_msg(msg, 4200)

    def _on_dl_cancelled(self, key):
        self.dl_states.pop(key, None)
        item = self.online_items.get(key)
        if item:
            try:
                cleanup_partial(self.lib.download_dir(), item)
            except Exception:
                pass
        self._dl_changed()
        self.toast_msg("Download cancelled.", 1800)

    def _online_menu(self, key, global_pos):
        item = self.online_items.get(key)
        if not item:
            return
        ic = ink(0.9)
        menu = style_menu(QMenu(self))
        target = self._local_copy(key) or key
        playing = target == self.current_path and self.engine.playing
        act_play = menu.addAction(qicon("pause" if playing else "play", ic, 16), "Pause" if playing else "Play")
        liked = self.lib.is_liked(key)
        act_like = menu.addAction(qicon("heart-fill" if liked else "heart", ic, 16),
                                  "Remove from favorites" if liked else "Add to favorites")
        sub = style_menu(menu.addMenu(qicon("list-plus", ic, 16), "Add to playlist"))
        pl_actions = {}
        for name in self.lib.playlist_names():
            a = sub.addAction(qicon("list-music", ic, 16), name)
            if key in self.lib.playlists[name]:
                a.setText(f"{name}  ✓")
                a.setEnabled(False)
            pl_actions[a] = name
        if pl_actions:
            sub.addSeparator()
        act_new_pl = sub.addAction(qicon("plus", ic, 16), "New playlist…")
        act_unplaylist = None
        if self.page == "collection" and self.current_collection in self.lib.playlists:
            act_unplaylist = menu.addAction(qicon("x", ic, 16), f"Remove from “{self.current_collection}”")
        menu.addSeparator()
        st = self.download_state(key)["state"]
        label = {"queued": "Cancel download", "downloading": "Cancel download", "done": "Downloaded"}.get(st, "Download")
        act_dl = menu.addAction(qicon("download", ic, 16), label)
        act_dl.setEnabled(st != "done")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        self.lib.register_online(item)
        if chosen == act_play:
            if target == self.current_path:
                self.toggle_play()
            elif self.page == "collection" and key in self.tracklist.paths():
                self._play_from_list(key)
            elif key in self.queue_paths:
                self.play_any(key)
            else:
                self.play_online_key(key)
        elif chosen == act_like:
            self.toggle_like_path(key)
        elif chosen == act_new_pl:
            self.create_playlist(add_path=key)
        elif chosen in pl_actions:
            self.add_to_playlist(pl_actions[chosen], key)
        elif chosen == act_unplaylist:
            self.lib.remove_from_playlist(self.current_collection, key)
            self.save_soon()
            self.refresh_all()
        elif chosen == act_dl:
            self.request_download(key)

    # -- Discord ----------------------------------------------------------------------------------
    def sync_presence(self):
        pr = self.presence
        path = self.current_path
        if not path or not self.engine.playing or self.loading_key == path:
            pr.clear()
            return
        item = self.online_items.get(path) if is_online(path) else None
        if item is None:
            for k, v in self.lib.downloads.items():
                if v == path:
                    item = self.online_items.get(k)
                    break
        try:
            pos = max(0, int(self.player.get_time()))
        except Exception:
            pos = 0
        pr.show(self.lib.title(path), self.lib.artist(path), "" if item else self.lib.album(path),
                duration_ms=self.lib.duration(path), position_ms=pos,
                image_url=item["cover_url"] if item else None)

    # -- online settings helpers ------------------------------------------------------------------
    def open_download_dir(self):
        d = self.lib.download_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def choose_download_dir(self, parent=None):
        folder = QFileDialog.getExistingDirectory(parent or self, "Choose download folder", str(self.lib.download_dir()))
        if folder:
            self.lib.settings["download_dir"] = folder
            self.save_soon()
        return folder

    def ffmpeg_available(self):
        try:
            return bool(find_ffmpeg())
        except Exception:
            return False

    def update_ytdlp(self):
        if getattr(sys, "frozen", False):
            self.toast_msg("Install the newest NILKON version to get the newest music engine.", 4200)
            return
        self.toast_msg("Updating the music engine…", 2000)

        def work():
            try:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                                   capture_output=True, text=True, timeout=300)
                ok = r.returncode == 0
                msg = ("Music engine updated. Restart NILKON to use it." if ok
                       else (r.stderr.strip().splitlines() or ["Update failed."])[-1])
            except Exception as exc:
                ok, msg = False, f"Update failed: {exc}"
            self._mb.post(self.ytdlpUpdated.emit, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _on_ytdlp_updated(self, ok, msg):
        self.toast_msg(msg, 4200)

    # -- song menu ------------------------------------------------------------------------------------
    def song_menu(self, path, global_pos):
        if is_online(path):
            self._online_menu(path, global_pos)
            return
        if path not in self.lib.tracks:
            return
        ic = ink(0.9)
        menu = style_menu(QMenu(self))
        is_cur_playing = path == self.current_path and self.engine.playing
        act_play = menu.addAction(qicon("pause" if is_cur_playing else "play", ic, 16),
                                  "Pause" if is_cur_playing else "Play")
        liked = self.lib.is_liked(path)
        act_like = menu.addAction(qicon("heart-fill" if liked else "heart", ic, 16),
                                  "Remove from favorites" if liked else "Add to favorites")
        act_rename = menu.addAction(qicon("edit", ic, 16), "Rename song…")
        menu.addSeparator()
        sub = style_menu(menu.addMenu(qicon("list-plus", ic, 16), "Add to playlist"))
        pl_actions = {}
        for name in self.lib.playlist_names():
            a = sub.addAction(qicon("list-music", ic, 16), name)
            if path in self.lib.playlists[name]:
                a.setText(f"{name}  ✓")
                a.setEnabled(False)
            pl_actions[a] = name
        if pl_actions:
            sub.addSeparator()
        act_new_pl = sub.addAction(qicon("plus", ic, 16), "New playlist…")
        act_unplaylist = None
        if self.page == "collection" and self.current_collection in self.lib.playlists:
            act_unplaylist = menu.addAction(qicon("x", ic, 16), f"Remove from “{self.current_collection}”")
        act_eq = menu.addAction(qicon("eq", ic, 16), "Customize equalizer for this song…")
        menu.addSeparator()
        act_remove = menu.addAction(qicon("x", ic, 16), "Remove from library")
        act_delete = menu.addAction(qicon("trash", ic, 16), "Delete file…")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_play:
            if path == self.current_path:
                self.toggle_play()
            else:
                self._play_in_context(path)
        elif chosen == act_like:
            self.toggle_like_path(path)
        elif chosen == act_rename:
            self.rename_song(path)
        elif chosen == act_new_pl:
            self.create_playlist(add_path=path)
        elif chosen in pl_actions:
            self.add_to_playlist(pl_actions[chosen], path)
        elif chosen == act_unplaylist:
            self.lib.remove_from_playlist(self.current_collection, path)
            self.save_soon()
            self.refresh_all()
        elif chosen == act_eq:
            self.open_equalizer(path, song_scope=True)
        elif chosen == act_remove:
            self.remove_song(path, delete_file=False)
        elif chosen == act_delete:
            self.remove_song(path, delete_file=True)

    def _play_in_context(self, path):
        if self.page == "collection" and path in self.tracklist.paths():
            self._play_from_list(path)
        else:
            self.play_any(path)

    def rename_song(self, path):
        current = self.lib.title(path)
        text, ok = ask_text(self, "Rename song", "Only the name shown in NILKON changes, not the file. "
                            "Leave it empty to restore the original name.", text=current, ok_text="Save")
        if not ok:
            return
        self.lib.rename(path, text)
        self.save_soon()
        self._update_now_labels() if path == self.current_path else None
        self.refresh_queue()
        self.refresh_home()
        if self.page == "collection":
            self.refresh_collection()
        self.repaint_lists()
        self.toast_msg("Song renamed", 1600)

    def remove_song(self, path, delete_file):
        name = self.lib.title(path)
        if delete_file:
            if not confirm(self, "Delete file", f"Move “{name}” to the Recycle Bin? "
                           "It will be removed from your computer and from NILKON.", "Delete file", "trash"):
                return
        elif not confirm(self, "Remove from library", f"Remove “{name}” from NILKON? The file stays on your computer.",
                         "Remove", "x"):
            return
        was_current = path == self.current_path
        if was_current:
            self.player.stop()
            self.player.set_media(None)   # release the file so Windows lets us delete it
            self.analyzer.cancel()
        if delete_file:
            ok = QFile(path).moveToTrash()
            if not ok:
                self.toast_msg("Could not move the file to the Recycle Bin.", 3600)
                if was_current:
                    self.play_path(path, autoplay=False)
                return
        self.lib.remove_track(path)
        self.covers.forget(path)
        self.queue_paths = [p for p in self.queue_paths if p != path]
        self._play_stack = [p for p in self._play_stack if p != path]
        self._suggest = [p for p in self._suggest if p != path]
        if was_current:
            self.current_path = ""
            self.cover_pix = None
            self.engine.set_playing(False)
            self.engine.analysis = None
            self.turntable.set_cover(None)
            self.mini_disc.set_cover(None)
            self.seek.set_envelope(None)
            self.seek.setValue(0)
            self.elapsed.setText("0:00")
            self.duration.setText("0:00")
            self.play_btn.set_icon("play")
            self._reset_now_labels()
            self._sync_like_button()
        self.save_soon()
        self.refresh_all()
        self.toast_msg("File moved to Recycle Bin" if delete_file else "Removed from library", 2000)

    # -- playlists ----------------------------------------------------------------------------------------
    def create_playlist(self, add_path=None):
        name, ok = ask_text(self, "New playlist", "Give your playlist a name. You can add songs from the ⋯ menu.",
                            placeholder="e.g. Late night drive", ok_text="Create", icon="list-plus")
        if not ok:
            return None
        good, msg = self.lib.create_playlist(name)
        if not good:
            notice(self, "Can't create playlist", msg, "info")
            return None
        name = name.strip()
        if add_path:
            self.lib.add_to_playlist(name, add_path)
        self.save_soon()
        self.refresh_all()
        self.toast_msg(f"Playlist “{name}” created" + (" and song added" if add_path else ""))
        return name

    def add_to_playlist(self, name, path):
        if self.lib.add_to_playlist(name, path):
            self.toast_msg(f"Added to {name}")
        else:
            self.toast_msg(f"Already in {name}", 1800)
        self.save_soon()
        self.refresh_sidebar()
        if self.page == "collection" and self.current_collection == name:
            self.refresh_collection()

    def playlist_context_menu(self, pos):
        item = self.playlist_list.itemAt(pos)
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        ic = ink(0.9)
        menu = style_menu(QMenu(self))
        play = menu.addAction(qicon("play", ic, 16), "Play playlist")
        rename = menu.addAction(qicon("edit", ic, 16), "Rename playlist…")
        delete = menu.addAction(qicon("trash", ic, 16), "Delete playlist")
        chosen = menu.exec(self.playlist_list.viewport().mapToGlobal(pos))
        if chosen == play:
            paths = self.lib.collection(name)
            if paths:
                self._set_queue(paths, name)
                self.play_any(paths[0])
            else:
                self.toast_msg("This playlist is empty", 1800)
        elif chosen == rename:
            new, ok = ask_text(self, "Rename playlist", "Choose a new name for this playlist.", text=name,
                               ok_text="Save", icon="list-music")
            if ok and new.strip() != name:
                good, msg = self.lib.rename_playlist(name, new)
                if not good:
                    notice(self, "Can't rename playlist", msg)
                    return
                if self.current_collection == name:
                    self.current_collection = new.strip()
                if self.queue_name == name:
                    self.queue_name = new.strip()
                self.save_soon()
                self.refresh_all()
                if self.page == "collection":
                    self.collection_title.setText(self._collection_title(self.current_collection))
        elif chosen == delete:
            if confirm(self, "Delete playlist", f"Delete “{name}”? Your songs stay in the library.",
                       "Delete", "trash"):
                self.lib.delete_playlist(name)
                if self.current_collection == name:
                    self.current_collection = ALL
                if self.queue_name == name:
                    self.queue_name = None
                self.save_soon()
                self.refresh_all()

    def _order_changed(self, paths):
        name = self.current_collection
        if self.page != "collection" or self.search.text().strip() or name == RECENT:
            return
        if self.lib.reorder(name, paths):
            self.save_soon()
            if self.queue_name == name:
                self.queue_paths = self.lib.collection(name)
                self.refresh_queue()
        else:
            self.refresh_collection()

    # -- equalizer ---------------------------------------------------------------------------------------------
    def apply_eq_for(self, path):
        eq = self.lib.eq_for(path) if path else self.lib.eq
        self.engine.set_eq(eq["values"], eq["preamp"], eq["enabled"])
        try:
            vq = vlc.AudioEqualizer()
            if eq["enabled"]:
                vq.set_preamp(float(effective_preamp(eq)))
                count = vlc.libvlc_audio_equalizer_get_band_count()
                for i, value in enumerate(eq["values"][:count]):
                    vq.set_amp_at_index(float(value), i)
            self._vlc_eq = vq
            self.player.set_equalizer(vq)
        except Exception as exc:
            self.toast_msg(f"Equalizer unavailable: {exc}", 4000)
        label = "Off" if not eq["enabled"] else eq["preset"]
        own = bool(path) and path in self.lib.track_eq
        self.eq_btn.setText(f"Equalizer · {label}" + (" · this song" if own else ""))

    def _eq_presets_changed(self, presets):
        self.lib.eq_presets = {k: {"values": list(v["values"]), "preamp": int(v.get("preamp", 0))} for k, v in presets.items()}
        self.save_soon()

    def global_eq_changed(self):
        self.apply_eq_for(self.current_path)
        self.save_soon()

    def open_equalizer(self, path=None, song_scope=False):
        path = path or self.current_path
        title = self.lib.title(path) if path else ""
        own = self.lib.track_eq.get(path) if path else None
        start = "song" if (song_scope or own is not None) and path else "global"
        target = path

        def on_change(scope, eq):
            if scope == "song" and target:
                self.lib.set_track_eq(target, eq)
            else:
                self.lib.eq = copy.deepcopy(eq)
            if target == self.current_path or scope == "global":
                self.apply_eq_for(self.current_path)

        def on_reset():
            if target:
                self.lib.set_track_eq(target, None)
                self.apply_eq_for(self.current_path)

        dlg = EqualizerDialog(self, self.engine, self.lib.eq, target or "", title, own,
                              on_change=on_change, on_reset_song=on_reset, start_scope=start,
                              custom_presets=self.lib.eq_presets, on_presets=self._eq_presets_changed)
        dlg.exec()
        self.apply_eq_for(self.current_path)
        self.save_soon()

    # -- settings ------------------------------------------------------------------------------------------------
    def open_settings(self, page=0):
        SettingsDialog(self, self, page).exec()
        self.save_soon()

    def apply_all_settings(self):
        for key in ("mode", "accent", "background", "wave_style", "reduced_fx", "sync_offset", "wave_gain", "wave_smooth"):
            self.apply_setting(key, save=False)

    def apply_setting(self, key, save=True):
        s = self.lib.settings
        if key == "mode":
            T.set_mode(s["mode"])
            QApplication.instance().setStyleSheet(build_qss())
            self._search_action.setIcon(qicon("search", ink(0.60), 18))
            self._refresh_empty_icon()
            self.repaint_all()
        elif key in ("accent", "adaptive"):
            self._apply_theme_colour()
            if key == "accent":
                QApplication.instance().setStyleSheet(build_qss())
        elif key in ("background", "custom_bg", "bg_dim", "bg_blur"):
            self._apply_background()
        elif key == "wave_style":
            for wf in (self.home.wave, self.col_wave):
                wf.set_wave_style(s["wave_style"])
        elif key == "reduced_fx":
            self.engine.set_reduced(s["reduced_fx"])
        elif key == "sync_offset":
            self.engine.offset_ms = int(s["sync_offset"])
        elif key == "wave_gain":
            self.engine.gain = s["wave_gain"] / 100.0
        elif key == "wave_smooth":
            self.engine.smooth = s["wave_smooth"] / 100.0
        elif key == "title_song":
            meta = self.lib.meta.get(self.current_path) if self.current_path else None
            self._set_title(meta.get("title", "") if isinstance(meta, dict) and self.engine.playing else "")
        elif key == "cookie_browser":
            online.COOKIE_BROWSER[0] = s["cookie_browser"]
            online.forget_all()
        elif key in ("discord_enabled", "discord_app_id"):
            self.presence.configure(s["discord_enabled"], s["discord_app_id"])
            self._presence_sig = None
            self.sync_presence()
        if key == "background":
            self._apply_background()
        if save:
            self.save_soon()

    def _theme_follow(self):
        """Buttons, sliders and menus only repaint on events: when the accent colour moves (new song colours) repaint
        them while it eases, and once more when it has settled, so nothing keeps the old song's colour."""
        sig = (T.c1.rgb(), T.c2.rgb(), T.c3.rgb())
        if sig == self._theme_sig:
            return
        now = _time.monotonic()
        settled = T.settled()
        if settled or now - self._theme_t >= 0.12:
            self._theme_sig = sig
            self._theme_t = now
            self.repaint_all()

    def repaint_all(self):
        for w in self.findChildren(QWidget):
            w.update()

    @staticmethod
    def _superdark_pixmap(width=1600, height=1000):
        """Built-in 'Super Dark' backdrop: near-black with the faintest blue depth."""
        pm = QPixmap(width, height)
        q = QPainter(pm)
        g = QLinearGradient(0, 0, 0, height)
        g.setColorAt(0.0, QColor(1, 2, 7))
        g.setColorAt(1.0, QColor(0, 0, 2))
        q.fillRect(pm.rect(), g)
        rg = QRadialGradient(width * 0.5, height * 1.05, width * 0.55)
        rg.setColorAt(0.0, QColor(18, 40, 110, 70))
        rg.setColorAt(1.0, QColor(18, 40, 110, 0))
        q.fillRect(pm.rect(), rg)
        q.end()
        return pm

    def _background_file(self, key):
        s = self.lib.settings
        if key == "custom":
            return Path(s["custom_bg"]) if s["custom_bg"] else None
        return ASSETS / "backgrounds" / f"{key}.jpg"

    def _background_pixmap(self):
        key = self.lib.settings["background"]
        if key == "aurora":
            return None
        if key == "superdark":
            if "superdark" not in self._bg_cache:
                self._bg_cache["superdark"] = self._superdark_pixmap()
            return self._bg_cache["superdark"]
        f = self._background_file(key)
        if f is None or not f.is_file():
            return None
        k = str(f)
        if k not in self._bg_cache:
            pm = QPixmap(k)
            self._bg_cache[k] = None if pm.isNull() else pm
        return self._bg_cache[k]

    def _apply_background(self):
        s = self.lib.settings
        self.backdrop.orb_scale = 0.18 if s["background"] == "superdark" else 1.0
        self.backdrop.set_background(self._background_pixmap(), 0 if s["background"] == "superdark" else s["bg_dim"],
                                     s["bg_blur"])

    def background_preview(self, name):
        if name == "superdark":
            return self._superdark_pixmap(300, 190)
        f = self._background_file(name)
        if f is None or not f.is_file():
            return None
        k = "preview:" + str(f)
        if k not in self._bg_cache:
            pm = QPixmap(str(f))
            self._bg_cache[k] = None if pm.isNull() else pm.scaledToWidth(
                300, Qt.TransformationMode.SmoothTransformation)
        return self._bg_cache[k]

    def pick_custom_background(self, parent=None):
        f, _ = QFileDialog.getOpenFileName(parent or self, "Choose a background image", str(Path.home()), IMAGE_FILTER)
        if not f:
            return False
        pm = QPixmap(f)
        if pm.isNull():
            notice(parent or self, "Background", "This image could not be opened.")
            return False
        folder = self.lib.dir / "backgrounds"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("custom_*"):
                try:
                    old.unlink()
                except OSError:
                    pass
            dest = folder / f"custom_{int(_time.time())}{Path(f).suffix.lower()}"
            shutil.copyfile(f, dest)
        except OSError as exc:
            notice(parent or self, "Background", f"Could not save the image: {exc}")
            return False
        s = self.lib.settings
        s["custom_bg"] = str(dest)
        s["background"] = "custom"
        self._bg_cache = {k: v for k, v in self._bg_cache.items() if "custom_" not in k}
        self._apply_background()
        self.save_soon()
        return True

    def clear_recent(self):
        self.lib.history = []
        self.save_soon()
        self.refresh_all()
        self.toast_msg("Recently played cleared", 1800)

    def reset_listen_counts(self):
        self.lib.play_counts = {}
        self._suggest = self.lib.suggestions(12)
        self.save_soon()
        self.refresh_all()
        self.toast_msg("Listening statistics reset", 1800)

    # -- window events ----------------------------------------------------------------------------------------------
    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.engine.active = not self.isMinimized()
        super().changeEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move((self.centralWidget().width() - self.toast.width()) // 2,
                            self.centralWidget().height() - 150)
        if hasattr(self, "tracklist"):
            QTimer.singleShot(0, self._sync_header_inset)

    def closeEvent(self, event):
        try:
            if self.current_path and not is_online(self.current_path):
                tm = self.player.get_time()
                if tm >= 0:
                    self.lib.last_pos = tm
                self.lib.last_path = self.current_path
            self.lib.save()
            self.presence.stop()
            self.hub.close_all()
            self.jobs.close()
            self.remote_images.close()
            self.analyzer.close() if hasattr(self.analyzer, "close") else None
            self.analyzer.cancel()
            self.player.stop()
            self.covers.close()
            self._meta_pool.shutdown(wait=False, cancel_futures=True)
        finally:
            event.accept()


def main():
    crashlog.install(Path.home() / ".nilkon_music")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")      # keep the console clean
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nilkon.MusicPlayer")
        except Exception:
            pass
    # Cyclic garbage collection only ever runs on the GUI thread: a collection inside a worker thread
    # can destroy Qt wrapper objects at the wrong time and crash Qt on Windows.
    gc.disable()
    app = QApplication(sys.argv)
    gc_timer = QTimer()
    gc_ticks = [0]

    def collect():
        gc_ticks[0] += 1
        gc.collect(1 if gc_ticks[0] % 15 else 2)
    gc_timer.timeout.connect(collect)
    gc_timer.start(4000)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    base_font = QFont()
    base_font.setFamilies(FONT_FAMILIES)
    base_font.setPointSize(10)
    app.setFont(base_font)
    if vlc is None:
        QMessageBox.critical(None, "NILKON could not start",
                             "VLC media player is required for playback and equalizer support.\n\n"
                             "Install VLC (64-bit) from https://www.videolan.org/vlc/ then restart NILKON.\n\n"
                             f"Technical details: {VLC_ERROR}")
        return 1
    try:
        window = MusicPlayer()
    except Exception as exc:
        QMessageBox.critical(None, "NILKON could not start",
                             "Something went wrong while starting the player. Make sure VLC (64-bit) is installed.\n\n"
                             f"Technical details: {exc}")
        raise
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
