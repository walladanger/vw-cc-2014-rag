#!/usr/bin/env python3
"""Production web entry point."""
import os

from waitress import serve

def server_options(env=None):
    from cc_workshop.operations.config import load_runtime_config

    values = os.environ if env is None else env
    config = load_runtime_config(values)
    return {
        "host": config.bind_host,
        "port": config.port,
        "threads": int(values.get("WEB_THREADS", "8")),
    }


def main():
    from app import app

    serve(app, **server_options())


if __name__ == "__main__":
    main()
