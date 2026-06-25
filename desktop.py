#!/usr/bin/env python3
"""Native Windows launcher for CC Workshop."""
import os
import socket
import sys
import threading
from pathlib import Path


def _app_data_dir():
    root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    path = root / "CC Workshop"
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _app_data_dir()
os.environ.setdefault("VW_RAG_OUT", str(DATA_DIR / "out"))
os.environ.setdefault("EMBEDDER", "ollama")
os.environ["CC_WORKSHOP_DESKTOP"] = "1"
Path(os.environ["VW_RAG_OUT"]).mkdir(parents=True, exist_ok=True)

from app import app  # noqa: E402


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
    main()
