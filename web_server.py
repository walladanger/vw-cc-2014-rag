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
    from cc_workshop.operations.instance_lock import InstanceAlreadyRunning, InstanceLock
    from cc_workshop.operations.paths import default_data_root
    lock = InstanceLock(default_data_root())
    try:
        lock.acquire()
    except InstanceAlreadyRunning as exc:
        raise SystemExit(f"CC Workshop is already running for this data folder: {exc}") from exc
    try:
        from app import app
        serve(app, **server_options())
    finally:
        lock.release()


if __name__ == "__main__":
    main()
