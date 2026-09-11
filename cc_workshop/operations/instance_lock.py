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
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.data_root.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(str(self.lock_path), flags)
        except FileExistsError as exc:
            raise InstanceAlreadyRunning(f"CC Workshop is already using {self.data_root}") from exc
        os.write(self._fd, str(os.getpid()).encode("ascii"))

    def release(self) -> None:
        if self._fd is None:
            return
        os.close(self._fd)
        self._fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
