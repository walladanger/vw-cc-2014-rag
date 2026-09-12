"""Model asset manifests, offline imports, and hardware profile selection.

This module is deliberately local-first. It validates files already present on
 disk and records exact asset identity before any model can be activated.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/+-]*$")
_ALLOWED_MODALITIES = frozenset({"text", "vision", "embedding"})
_ALLOWED_DEVICE_KINDS = frozenset({"cpu", "gpu"})


class ModelAssetError(RuntimeError):
    """Raised when a model manifest or local asset fails validation."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def _required_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_identifier(value: Any, field: str) -> str:
    text = _required_string(value, field)
    if not _IDENTIFIER_RE.match(text) or PureWindowsPath(text).drive or any(part in {"..", ".", ""} for part in text.split("/")):
        raise ValueError(f"{field} contains unsupported characters")
    return text


def _safe_relative_path(filename: str) -> Path:
    raw = _required_string(filename, "filename")
    candidate = Path(raw)
    if candidate.is_absolute() or PureWindowsPath(raw).drive or ".." in PureWindowsPath(raw).parts:
        raise ModelAssetError("UNSAFE_ASSET_PATH", "asset filename must stay inside the offline kit")
    if not candidate.name:
        raise ModelAssetError("UNSAFE_ASSET_PATH", "asset filename must name a file")
    return candidate


def _resolve_beneath(root: Path, *parts: str | Path) -> Path:
    root_resolved = Path(root).expanduser().resolve()
    candidate = root_resolved.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ModelAssetError("UNSAFE_ASSET_PATH", "resolved asset path escapes its root") from exc
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ModelAsset:
    filename: str
    sha256: str
    size_bytes: int
    role: str
    required_for: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ModelAsset":
        filename = str(_safe_relative_path(raw.get("filename")).as_posix())
        sha256 = _required_string(raw.get("sha256"), "sha256").lower()
        if not _SHA256_RE.match(sha256):
            raise ValueError("sha256 must be a 64-character hex digest")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("size_bytes must be a positive integer")
        role = _required_identifier(raw.get("role", "weights"), "role")
        required_for_raw = raw.get("required_for", ())
        if isinstance(required_for_raw, (str, bytes)):
            raise TypeError("required_for must be an iterable of modality strings")
        required: list[str] = []
        seen: set[str] = set()
        for item in required_for_raw:
            value = _required_string(item, "required_for")
            if value not in _ALLOWED_MODALITIES:
                raise ValueError(f"unsupported required_for modality: {value}")
            if value not in seen:
                seen.add(value)
                required.append(value)
        return cls(filename=filename, sha256=sha256, size_bytes=size, role=role, required_for=tuple(required))

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "role": self.role,
            "required_for": list(self.required_for),
        }


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    revision: str
    family: str
    modality: str
    license: str
    runtime: str
    assets: tuple[ModelAsset, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ModelManifest":
        model_id = _required_identifier(raw.get("model_id"), "model_id")
        revision = _required_identifier(raw.get("revision"), "revision")
        family = _required_identifier(raw.get("family"), "family")
        modality = _required_string(raw.get("modality"), "modality")
        if modality not in _ALLOWED_MODALITIES:
            raise ValueError(f"unsupported modality: {modality}")
        license_name = _required_string(raw.get("license"), "license")
        runtime = _required_identifier(raw.get("runtime", "llama.cpp"), "runtime")
        assets_raw = raw.get("assets", ())
        if isinstance(assets_raw, (str, bytes)) or not isinstance(assets_raw, Iterable):
            raise TypeError("assets must be an iterable of asset records")
        assets = tuple(ModelAsset.from_dict(item) for item in assets_raw)
        if not assets:
            raise ValueError("at least one asset is required")
        if len({a.filename.casefold() for a in assets}) != len(assets):
            raise ModelAssetError("DUPLICATE_ASSET", "asset destinations must be unique")
        return cls(model_id, revision, family, modality, license_name, runtime, assets)

    @property
    def requires_vision(self) -> bool:
        return self.modality == "vision" or any("vision" in asset.required_for for asset in self.assets)

    @property
    def has_projector(self) -> bool:
        return any(asset.role == "projector" and "vision" in asset.required_for for asset in self.assets)

    @property
    def manifest_key(self) -> str:
        digest = hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "family": self.family,
            "modality": self.modality,
            "license": self.license,
            "runtime": self.runtime,
            "assets": [asset.to_dict() for asset in self.assets],
        }


@dataclass(frozen=True, slots=True)
class InstalledModel:
    model_id: str
    revision: str
    family: str
    modality: str
    license: str
    runtime: str
    install_root: Path
    assets: tuple[ModelAsset, ...]

    @property
    def manifest_path(self) -> Path:
        return self.install_root / "manifest.json"

    def verify(self) -> tuple[Path, Path | None]:
        expected = ModelManifest(self.model_id, self.revision, self.family, self.modality, self.license, self.runtime, self.assets)
        actual = ModelManifest.from_dict(json.loads(self.manifest_path.read_text(encoding="utf-8")))
        if actual != expected:
            raise ModelAssetError("MANIFEST_MISMATCH", "installed manifest identity changed")
        if expected.requires_vision and not expected.has_projector:
            raise ModelAssetError("VISION_PROJECTOR_MISSING", "vision requires its manifest projector")
        weights = []; projectors = []
        for asset in self.assets:
            path = _resolve_beneath(self.install_root, "assets", _safe_relative_path(asset.filename))
            _verify_asset(path, asset)
            if asset.role == "weights": weights.append(path)
            if asset.role == "projector": projectors.append(path)
        if len(weights) != 1 or len(projectors) > 1:
            raise ModelAssetError("ASSET_ROLE_INVALID", "activation requires one weights file and at most one projector")
        return weights[0], projectors[0] if projectors else None


def _verify_asset(path: Path, asset: ModelAsset) -> None:
    if not path.is_file(): raise ModelAssetError("ASSET_MISSING", "installed asset is missing")
    if path.stat().st_size != asset.size_bytes: raise ModelAssetError("ASSET_SIZE_MISMATCH", "asset size mismatch")
    if _sha256_file(path) != asset.sha256: raise ModelAssetError("ASSET_HASH_MISMATCH", "asset hash mismatch")


class ModelAssetStore:
    """Validates and imports model assets from an offline kit directory."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def import_offline(self, manifest: ModelManifest, source_dir: Path) -> InstalledModel:
        if manifest.requires_vision and not manifest.has_projector:
            raise ModelAssetError("VISION_PROJECTOR_MISSING", "vision models require a matching projector asset")
        source_root = Path(source_dir).expanduser().resolve()
        if not source_root.is_dir():
            raise ModelAssetError("OFFLINE_KIT_MISSING", "offline model kit directory does not exist")

        # Logical repository IDs never become path components.
        manifest = ModelManifest.from_dict(manifest.to_dict())
        install_root = _resolve_beneath(self.root, manifest.manifest_key)
        staging_root = Path(tempfile.mkdtemp(prefix="import-", dir=self.root))
        staging_assets = staging_root / "assets"
        staging_assets.mkdir()

        try:
            for asset in manifest.assets:
                rel = _safe_relative_path(asset.filename)
                source_path = _resolve_beneath(source_root, rel)
                if not source_path.is_file():
                    raise ModelAssetError("ASSET_MISSING", f"asset is missing: {asset.filename}")
                actual_size = source_path.stat().st_size
                if actual_size != asset.size_bytes:
                    raise ModelAssetError("ASSET_SIZE_MISMATCH", f"asset size mismatch: {asset.filename}")
                actual_sha = _sha256_file(source_path)
                if actual_sha.lower() != asset.sha256.lower():
                    raise ModelAssetError("ASSET_HASH_MISMATCH", f"asset hash mismatch: {asset.filename}")
                target_path = _resolve_beneath(staging_assets, rel)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                _verify_asset(target_path, asset)

            (staging_root / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if install_root.exists():
                existing = InstalledModel(manifest.model_id, manifest.revision, manifest.family, manifest.modality, manifest.license, manifest.runtime, install_root, manifest.assets)
                existing.verify()
                shutil.rmtree(staging_root)
            else:
                staging_root.replace(install_root)
        except Exception:
            if staging_root.exists():
                shutil.rmtree(staging_root)
            raise

        return InstalledModel(
            model_id=manifest.model_id,
            revision=manifest.revision,
            family=manifest.family,
            modality=manifest.modality,
            license=manifest.license,
            runtime=manifest.runtime,
            install_root=install_root,
            assets=manifest.assets,
        )


@dataclass(frozen=True, slots=True)
class HardwareDevice:
    kind: str
    name: str
    memory_bytes: int | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        if kind not in _ALLOWED_DEVICE_KINDS:
            raise ValueError("hardware device kind must be 'cpu' or 'gpu'")
        name = _required_string(self.name, "name")
        memory = self.memory_bytes
        if memory is not None and (isinstance(memory, bool) or not isinstance(memory, int) or memory < 0):
            raise ValueError("memory_bytes must be a non-negative integer or None")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class HardwareInventory:
    devices: tuple[HardwareDevice, ...]

    def __post_init__(self) -> None:
        devices = tuple(self.devices)
        if not devices:
            devices = (HardwareDevice("cpu", "unknown CPU", None),)
        object.__setattr__(self, "devices", devices)

    @property
    def gpus(self) -> tuple[HardwareDevice, ...]:
        return tuple(device for device in self.devices if device.kind == "gpu")

    @property
    def cpus(self) -> tuple[HardwareDevice, ...]:
        return tuple(device for device in self.devices if device.kind == "cpu")


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    name: str
    device_ids: tuple[str, ...]
    settings: Mapping[str, Any]
    experimental: bool = False


def discover_hardware(runtime_probe: Callable[[], Mapping[str, Any] | Sequence[Mapping[str, Any]] | str]) -> HardwareInventory:
    """Build a hardware inventory from explicit runtime probe output.

    The probe can return a dict with a ``devices`` list, a list of device dicts,
    or a JSON string in either shape. No model-name heuristics are used.
    """
    raw = runtime_probe()
    if isinstance(raw, str):
        raw = json.loads(raw)
    records: Sequence[Mapping[str, Any]]
    if isinstance(raw, Mapping):
        records = raw.get("devices", ())  # type: ignore[assignment]
    else:
        records = raw
    devices: list[HardwareDevice] = []
    for record in records:
        kind = str(record.get("kind") or record.get("type") or "").lower()
        name = str(record.get("name") or record.get("description") or kind or "unknown")
        memory = record.get("memory_bytes", record.get("vram_bytes"))
        devices.append(HardwareDevice(kind, name, memory))
    return HardwareInventory(tuple(devices))


def recommended_profiles(manifest: ModelManifest, inventory: HardwareInventory) -> tuple[HardwareProfile, ...]:
    """Return conservative hardware profiles derived only from detected devices."""
    profiles: list[HardwareProfile] = []
    cpu_ids = [f"cpu:{index}" for index, _ in enumerate(inventory.cpus)]
    gpu_ids = [f"gpu:{index}" for index, _ in enumerate(inventory.gpus)]
    if cpu_ids or not gpu_ids:
        profiles.append(HardwareProfile(
            name="compact_cpu",
            device_ids=(cpu_ids[0] if cpu_ids else "cpu:0",),
            settings={"runtime": manifest.runtime, "gpu_layers": 0, "profile": "compact"},
        ))
    if gpu_ids:
        profiles.append(HardwareProfile(
            name="single_gpu",
            device_ids=(gpu_ids[0],),
            settings={"runtime": manifest.runtime, "split_mode": "none", "profile": "single_gpu"},
        ))
    if len(gpu_ids) >= 2:
        profiles.append(HardwareProfile(
            name="multiple_gpu",
            device_ids=tuple(gpu_ids),
            settings={"runtime": manifest.runtime, "split_mode": "layer", "profile": "multiple_gpu"},
            experimental=True,
        ))
    return tuple(profiles)
