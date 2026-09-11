"""llama.cpp sidecar process supervision.

The sidecar owns only child processes it started in the current application
session. Port conflicts with unrelated processes are reported, not killed.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


class SidecarError(RuntimeError):
    """Structured sidecar failure safe for UI and logs."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = str(code)
        self.retryable = bool(retryable)
        super().__init__(f"{self.code}: {message}")


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    executable_path: Path
    working_dir: Path
    version: str
    required_files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable_path", Path(self.executable_path).expanduser().resolve())
        object.__setattr__(self, "working_dir", Path(self.working_dir).expanduser().resolve())
        object.__setattr__(
            self,
            "required_files",
            tuple(Path(path).expanduser().resolve() for path in self.required_files),
        )
        if not str(self.version or "").strip():
            raise ValueError("runtime version is required")


@dataclass(frozen=True, slots=True)
class LlamaServerConfig:
    runtime: RuntimeSpec
    model_path: Path
    model_id: str
    role: str = "generation"
    host: str = "127.0.0.1"
    port: int = 8080
    context_size: int = 4096
    gpu_layers: int = 0
    extra_args: tuple[str, ...] = ()
    startup_timeout: float = 10.0
    poll_interval: float = 0.05
    shutdown_policy: str = "terminate"

    def __post_init__(self) -> None:
        role = str(self.role or "").strip()
        model_id = str(self.model_id or "").strip()
        host = str(self.host or "").strip()
        if not role:
            raise ValueError("role is required")
        if not model_id:
            raise ValueError("model_id is required")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("llama.cpp sidecar must bind to loopback")
        for name, value, lower, upper in (
            ("port", self.port, 1, 65535),
            ("context_size", self.context_size, 1, 10_000_000),
            ("gpu_layers", self.gpu_layers, 0, 10_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not (lower <= value <= upper):
                raise ValueError(f"{name} is out of range")
        if self.shutdown_policy not in {"terminate", "leave_running"}:
            raise ValueError("shutdown_policy must be 'terminate' or 'leave_running'")
        if isinstance(self.extra_args, (str, bytes)):
            raise TypeError("extra_args must be a sequence of strings")
        extra_args = tuple(str(arg) for arg in self.extra_args)
        if any(not arg for arg in extra_args):
            raise ValueError("extra_args cannot contain blank values")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "host", "127.0.0.1" if host == "localhost" else host)
        object.__setattr__(self, "model_path", Path(self.model_path).expanduser().resolve())
        object.__setattr__(self, "extra_args", extra_args)

    @property
    def base_url(self) -> str:
        if self.host == "::1":
            return f"http://[::1]:{self.port}/v1"
        return f"http://{self.host}:{self.port}/v1"

    def command(self) -> tuple[str, ...]:
        return (
            str(self.runtime.executable_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--model",
            str(self.model_path),
            "--ctx-size",
            str(self.context_size),
            "--n-gpu-layers",
            str(self.gpu_layers),
            *self.extra_args,
        )


@dataclass(frozen=True, slots=True)
class PortStatus:
    in_use: bool
    owner_pid: int | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ready: bool
    model_ids: tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_ids", tuple(str(model) for model in self.model_ids))


@dataclass(frozen=True, slots=True)
class SidecarState:
    role: str
    pid: int
    token: str
    base_url: str
    model_id: str
    runtime_version: str
    command: tuple[str, ...]
    started_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "pid": self.pid,
            "token": self.token,
            "base_url": self.base_url,
            "model_id": self.model_id,
            "runtime_version": self.runtime_version,
            "command": list(self.command),
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SidecarState":
        return cls(
            role=str(raw["role"]),
            pid=int(raw["pid"]),
            token=str(raw["token"]),
            base_url=str(raw["base_url"]),
            model_id=str(raw["model_id"]),
            runtime_version=str(raw["runtime_version"]),
            command=tuple(str(item) for item in raw["command"]),
            started_at=float(raw["started_at"]),
        )


def _default_process_factory(command: Sequence[str], cwd: Path, env: Mapping[str, str]) -> ProcessHandle:
    import subprocess

    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": dict(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.Popen(list(command), **kwargs)


def _default_port_probe(host: str, port: int) -> PortStatus:
    import socket

    target_host = "::1" if host == "::1" else host
    family = socket.AF_INET6 if target_host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        result = sock.connect_ex((target_host, int(port)))
    return PortStatus(result == 0, None)


def _default_readiness_probe(base_url: str) -> ProbeResult:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return ProbeResult(False, (), str(exc))
    model_ids = tuple(str(item.get("id", "")) for item in payload.get("data", ()) if item.get("id"))
    return ProbeResult(bool(model_ids), model_ids, "ready")


class LlamaSidecarManager:
    """Start, probe, record and close one llama.cpp server process."""

    def __init__(
        self,
        config: LlamaServerConfig,
        *,
        state_path: Path,
        process_factory: Callable[[Sequence[str], Path, Mapping[str, str]], ProcessHandle] | None = None,
        port_probe: Callable[[str, int], PortStatus] | None = None,
        readiness_probe: Callable[[str], ProbeResult] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        environment: Mapping[str, str] | None = None,
    ):
        self.config = config
        self.state_path = Path(state_path).expanduser().resolve()
        self.process_factory = process_factory or _default_process_factory
        self.port_probe = port_probe or _default_port_probe
        self.readiness_probe = readiness_probe or _default_readiness_probe
        self.sleep = sleep
        self.environment = dict(os.environ if environment is None else environment)
        self._process: ProcessHandle | None = None
        self._state: SidecarState | None = None

    def start(self) -> SidecarState:
        if self._process is not None and self._process.poll() is None and self._state is not None:
            return self._state

        self._validate_runtime_files()
        port = self.port_probe(self.config.host, self.config.port)
        if port.in_use:
            raise SidecarError(
                "PORT_IN_USE",
                f"{self.config.host}:{self.config.port} is already in use by another process",
                retryable=False,
            )

        command = self.config.command()
        process = self.process_factory(command, self.config.runtime.working_dir, self._child_environment())
        self._process = process
        self._state = SidecarState(
            role=self.config.role,
            pid=int(process.pid),
            token=uuid.uuid4().hex,
            base_url=self.config.base_url,
            model_id=self.config.model_id,
            runtime_version=self.config.runtime.version,
            command=tuple(command),
            started_at=time.time(),
        )
        self._write_state(self._state)

        deadline = time.monotonic() + float(self.config.startup_timeout)
        while time.monotonic() <= deadline:
            exit_code = process.poll()
            if exit_code is not None:
                self._clear_state()
                self._state = None
                raise SidecarError("CHILD_EXITED", f"llama.cpp exited before readiness: {exit_code}", retryable=True)
            probe = self.readiness_probe(self.config.base_url)
            if probe.ready:
                if self.config.model_id not in probe.model_ids:
                    self._terminate_owned_process()
                    self._clear_state()
                    self._state = None
                    raise SidecarError(
                        "MODEL_IDENTITY_MISMATCH",
                        "ready endpoint did not report the configured model identity",
                        retryable=True,
                    )
                return self._state
            self.sleep(float(self.config.poll_interval))

        self._terminate_owned_process()
        self._clear_state()
        self._state = None
        raise SidecarError("READINESS_TIMEOUT", "llama.cpp did not become ready before the timeout", retryable=True)

    def close(self) -> None:
        if self.config.shutdown_policy == "leave_running":
            self._process = None
            return
        self._terminate_owned_process()
        self._clear_state()
        self._state = None
        self._process = None

    def __enter__(self) -> "LlamaSidecarManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _validate_runtime_files(self) -> None:
        runtime = self.config.runtime
        if not runtime.executable_path.is_file():
            raise SidecarError("RUNTIME_MISSING", "llama.cpp server executable is missing", retryable=False)
        if not runtime.working_dir.is_dir():
            raise SidecarError("RUNTIME_MISSING", "llama.cpp working directory is missing", retryable=False)
        if not self.config.model_path.is_file():
            raise SidecarError("MODEL_MISSING", "configured model file is missing", retryable=False)
        for required in runtime.required_files:
            if not required.is_file():
                raise SidecarError("RUNTIME_MISSING", f"required runtime file is missing: {required.name}", retryable=False)

    def _child_environment(self) -> Mapping[str, str]:
        env = dict(self.environment)
        env.setdefault("LLAMA_LOG_PREFIX", "1")
        return env

    def _read_all_states(self) -> dict[str, SidecarState]:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SidecarError("STATE_CORRUPT", "sidecar ownership registry is corrupt", retryable=False) from exc
        return {str(key): SidecarState.from_dict(value) for key, value in raw.items()}

    def _write_state(self, state: SidecarState) -> None:
        states = self._read_all_states()
        states[state.role] = state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({key: value.to_dict() for key, value in states.items()}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _clear_state(self) -> None:
        if not self.state_path.exists():
            return
        states = self._read_all_states()
        states.pop(self.config.role, None)
        if states:
            self.state_path.write_text(
                json.dumps({key: value.to_dict() for key, value in states.items()}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            self.state_path.unlink()

    def _terminate_owned_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2.0)
