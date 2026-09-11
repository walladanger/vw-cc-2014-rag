"""Writable application path selection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class UnsafePathError(ValueError):
    """Raised when a requested path would escape its allowed storage root."""


@dataclass(frozen=True, slots=True)
class DataPaths:
    root: Path
    registry_db: Path
    configuration: Path
    models: Path
    shared_sources: Path
    staging: Path
    jobs: Path
    logs: Path
    backups: Path
    garages: Path


def resolve_within(root: Path, *parts: str | os.PathLike[str]) -> Path:
    """Resolve a path beneath *root* and reject traversal, absolute, or symlink escapes."""

    resolved_root = Path(root).expanduser().resolve()
    candidate = resolved_root
    for part in parts:
        path = Path(part).expanduser()
        candidate = path if path.is_absolute() else candidate / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes storage root: {resolved}") from exc
    return resolved


def default_data_root(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    explicit = str(values.get("CC_WORKSHOP_DATA_ROOT", "")).strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    local_app_data = str(values.get("LOCALAPPDATA", "")).strip()
    parent = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    return (parent / "CC Workshop").resolve()


def initialize_data_root(root: Path) -> DataPaths:
    resolved = Path(root).expanduser().resolve()
    paths = DataPaths(
        root=resolved,
        registry_db=resolved / "registry.sqlite",
        configuration=resolved / "configuration",
        models=resolved / "models",
        shared_sources=resolved / "shared_sources",
        staging=resolved / "staging",
        jobs=resolved / "jobs",
        logs=resolved / "logs",
        backups=resolved / "backups",
        garages=resolved / "garages",
    )
    for directory in (
        paths.root,
        paths.configuration,
        paths.models,
        paths.shared_sources,
        paths.staging,
        paths.jobs,
        paths.logs,
        paths.backups,
        paths.garages,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in ("originals", "derivatives", "indexes"):
        (paths.shared_sources / directory).mkdir(exist_ok=True)
    return paths
