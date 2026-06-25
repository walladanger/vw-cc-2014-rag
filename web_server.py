#!/usr/bin/env python3
"""Production web entry point."""
import os

from waitress import serve

from app import app


if __name__ == "__main__":
    serve(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        threads=int(os.environ.get("WEB_THREADS", "8")),
    )
