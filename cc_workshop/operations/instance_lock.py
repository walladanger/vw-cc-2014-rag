"""Single-instance ownership for a CC Workshop data root."""

from __future__ import annotations

import os
from pathlib import Path


class InstanceAlreadyRunning(RuntimeError):
    """Raised when another process already owns the same data root."""


class InstanceLock:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).expanduser().resolve()
        self.lock_path = self.data_root / ".cc_workshop.lock"
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.data_root.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(self.lock_path, "a+b")
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if "handle" in locals():
                handle.close()
            raise InstanceAlreadyRunning(f"CC Workshop is already using {self.data_root}") from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
