"""Crash diagnostics: Python errors and hard crashes are written to <data dir>/crash.log."""
import faulthandler
import sys
import threading
import time
import traceback
from pathlib import Path

_file = None


def install(folder):
    """Call once at start-up. Never raises."""
    global _file
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "crash.log"
        if log.exists() and log.stat().st_size > 256 * 1024:
            log.write_text("", encoding="utf-8")
        _file = open(log, "a", buffering=1, encoding="utf-8")
        _file.write(f"\n=== NILKON started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        faulthandler.enable(file=_file, all_threads=True)
    except Exception:
        _file = None

    def write(kind, exc_type, exc, tb):
        try:
            if _file is not None:
                _file.write(f"--- {kind} {time.strftime('%H:%M:%S')} ---\n")
                _file.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    def hook(exc_type, exc, tb):
        write("error", exc_type, exc, tb)
        try:
            if sys.stderr is not None:
                sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    def thread_hook(args):
        write(f"thread {getattr(args.thread, 'name', '?')}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
