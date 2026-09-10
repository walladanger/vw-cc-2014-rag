#!/usr/bin/env python3
"""Native Windows launcher for CC Workshop."""
import os
import socket
import sys
import threading
from pathlib import Path

from cc_workshop.operations.paths import default_data_root, initialize_data_root


DATA_PATHS = initialize_data_root(default_data_root())
DATA_DIR = DATA_PATHS.root

# Under pythonw.exe stdout/stderr are None; any print() would crash the app.
# Redirect them to a log file before importing anything that prints.
if sys.stdout is None or sys.stderr is None:
    _log_dir = DATA_PATHS.logs
    _log = open(_log_dir / "desktop.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log
    import faulthandler
    faulthandler.enable(file=_log)


def _crumb(msg):
    with open(DATA_PATHS.logs / "boot.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")


_crumb("start")


os.environ.setdefault("VW_RAG_OUT", str(DATA_DIR / "out"))
os.environ.setdefault("EMBEDDER", "local")
os.environ["CC_WORKSHOP_DESKTOP"] = "1"
Path(os.environ["VW_RAG_OUT"]).mkdir(parents=True, exist_ok=True)

_crumb("env set, importing app")
from app import app  # noqa: E402
_crumb("app imported")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class DesktopApi:
    def open_data_folder(self):
        os.startfile(os.environ["VW_RAG_OUT"])
        return True

    def data_folder(self):
        return os.environ["VW_RAG_OUT"]


def _style_title_bar():
    """Match the window caption to the app's accent blue (#3888ff).
    Windows 11 DWM: DWMWA_CAPTION_COLOR=35, DWMWA_TEXT_COLOR=36 (COLORREF 0x00BBGGRR)."""
    import ctypes
    import time
    from ctypes import wintypes

    try:
        user32 = ctypes.WinDLL("user32")
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.restype = ctypes.HRESULT
        dwm.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]

        hwnd = None
        for _ in range(50):  # window can take a moment to exist
            hwnd = user32.FindWindowW(None, "CC Workshop")
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        caption = wintypes.DWORD(0x00FF8838)  # BGR of #3888ff
        text    = wintypes.DWORD(0x00FFFFFF)  # white title text
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
    except Exception:
        pass  # cosmetic only — never take the app down over a title bar


def main():
    import webview
    from waitress import serve

    port = _free_port()
    server = threading.Thread(
        target=serve,
        kwargs={"app": app, "host": "127.0.0.1", "port": port, "threads": 8},
        daemon=True,
    )
    server.start()

    webview.create_window(
        "CC Workshop",
        f"http://127.0.0.1:{port}",
        js_api=DesktopApi(),
        width=1440,
        height=900,
        min_size=(960, 640),
        background_color="#0a0e13",
    )
    webview.start(_style_title_bar, debug="--debug" in sys.argv)


if __name__ == "__main__":
    _crumb("calling main")
    try:
        main()
        _crumb("main returned (window closed)")
    except BaseException as exc:
        import traceback
        _crumb("CRASH: " + repr(exc))
        _crumb(traceback.format_exc())
        raise
