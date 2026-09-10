"""Runtime settings with local-only defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .paths import default_data_root


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    data_root: Path
    bind_host: str = "127.0.0.1"
    port: int = 5000


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    values = os.environ if env is None else env
    host = str(values.get("CC_WORKSHOP_BIND_HOST", values.get("HOST", "127.0.0.1"))).strip()
    if not host:
        raise ValueError("bind host cannot be blank")
    try:
        port = int(values.get("PORT", "5000"))
    except (TypeError, ValueError) as exc:
        raise ValueError("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return RuntimeConfig(data_root=default_data_root(values), bind_host=host, port=port)
