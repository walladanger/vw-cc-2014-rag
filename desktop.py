#!/usr/bin/env python3
"""Native Windows launcher for CC Workshop."""
import os
import socket
import sys
import threading
from pathlib import Path

# Under pythonw.exe stdout/stderr are None; any print() would crash the app.
# Redirect them to a log file before importing anything that prints.
if sys.stdout is None or sys.stderr is None:
    _log_dir = Path(__file__).resolve().parent / "logs"
    _log_dir.mkdir(exist_ok=True)
    _log = open(_log_dir / "desktop.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log


def _crumb(msg):
    with open(Path(__file__).resolve().parent / "logs" / "boot.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")


_crumb("start")


def _app_data_dir():
    # Portable layout: prefer an out/ folder sitting next to this script
    # (app + data travel together on a USB drive or copied folder).
    local_out = Path(__file__).resolve().parent / "out"
    if local_out.is_dir():
        return local_out.parent
    root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    path = root / "CC Workshop"
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _app_data_dir()
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
    webview.start(debug="--debug" in sys.argv)


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
