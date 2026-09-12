"""Inference runtime settings and activation guards.

Profiles are staged, validated, activated, then persisted. A failed change never
replaces the last working profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .inference import EndpointConfig, ProviderError

_SIDE_MODES = frozenset({"sidecar", "external"})
_SPLIT_MODES = frozenset({"none", "layer", "tensor"})
_KV_CACHE_PRECISIONS = frozenset({"f16", "q8_0", "q4_0", "q4_1"})


class InferenceSettingsError(RuntimeError):
    """Structured settings failure safe for UI and logs."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = str(code)
        self.retryable = bool(retryable)
        super().__init__(f"{self.code}: {message}")


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    runtime_version: str
    allow_quantized_kv_with_tensor_split: bool = False

    def __post_init__(self) -> None:
        if not str(self.runtime_version or "").strip():
            raise ValueError("runtime_version is required")


@dataclass(frozen=True, slots=True)
class EndpointProbeResult:
    ready: bool
    base_url: str
    redirect_target: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HardwareSettings:
    context_size: int
    gpu_layers: int
    split_mode: str = "none"
    tensor_split: tuple[float, ...] = ()
    kv_cache_precision: str = "f16"
    flash_attention: bool = False
    cpu_threads: int | None = None
    generation_limit: int | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], policy: RuntimePolicy) -> "HardwareSettings":
        def int_range(field: str, lower: int, upper: int) -> int:
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not (lower <= value <= upper):
                raise InferenceSettingsError("INVALID_HARDWARE_SETTING", f"{field} is out of range")
            return value

        context_size = int_range("context_size", 1, 10_000_000)
        gpu_layers = int_range("gpu_layers", 0, 10_000)
        split_mode = str(raw.get("split_mode", "none") or "none").strip().lower()
        if split_mode not in _SPLIT_MODES:
            raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "split_mode is unsupported")
        kv_cache = str(raw.get("kv_cache_precision", "f16") or "f16").strip().lower()
        if kv_cache not in _KV_CACHE_PRECISIONS:
            raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "kv_cache_precision is unsupported")
        tensor_split = _parse_tensor_split(raw.get("tensor_split", ()), split_mode)
        if split_mode == "tensor" and kv_cache != "f16" and not policy.allow_quantized_kv_with_tensor_split:
            raise InferenceSettingsError(
                "INVALID_RUNTIME_COMBINATION",
                "the pinned llama.cpp build does not allow quantized KV cache with tensor splitting",
            )
        cpu_threads = _optional_positive_int(raw.get("cpu_threads"), "cpu_threads")
        generation_limit = _optional_positive_int(raw.get("generation_limit"), "generation_limit")
        return cls(
            context_size=context_size,
            gpu_layers=gpu_layers,
            split_mode=split_mode,
            tensor_split=tensor_split,
            kv_cache_precision=kv_cache,
            flash_attention=bool(raw.get("flash_attention", False)),
            cpu_threads=cpu_threads,
            generation_limit=generation_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_size": self.context_size,
            "gpu_layers": self.gpu_layers,
            "split_mode": self.split_mode,
            "tensor_split": list(self.tensor_split),
            "kv_cache_precision": self.kv_cache_precision,
            "flash_attention": self.flash_attention,
            "cpu_threads": self.cpu_threads,
            "generation_limit": self.generation_limit,
        }


@dataclass(frozen=True, slots=True)
class RoleSettings:
    role: str
    mode: str
    model_id: str
    endpoint: EndpointConfig | None = None

    @classmethod
    def from_dict(cls, role: str, raw: Mapping[str, Any], revision: str) -> "RoleSettings":
        mode = str(raw.get("mode", "sidecar") or "sidecar").strip().lower()
        if mode not in _SIDE_MODES:
            raise InferenceSettingsError("INVALID_ENDPOINT_MODE", f"{role} mode is unsupported")
        model_id = _required_text(raw.get("model_id"), f"{role}.model_id")
        endpoint = None
        if mode == "external":
            try:
                endpoint = EndpointConfig(
                    provider_id=f"external-{role}",
                    role=role,
                    endpoint=_required_text(raw.get("endpoint"), f"{role}.endpoint"),
                    config_revision=revision,
                )
            except (ProviderError, ValueError) as exc:
                raise InferenceSettingsError("INVALID_ENDPOINT", "external endpoints must be loopback or private-network URLs") from exc
        return cls(role=role, mode=mode, model_id=model_id, endpoint=endpoint)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"mode": self.mode, "model_id": self.model_id}
        if self.endpoint is not None:
            data["endpoint"] = self.endpoint.base_url
        return data


@dataclass(frozen=True, slots=True)
class InferenceProfile:
    name: str
    revision: str
    generation: RoleSettings
    embeddings: RoleSettings
    hardware: HardwareSettings

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], policy: RuntimePolicy) -> "InferenceProfile":
        name = _required_identifier(raw.get("name"), "name")
        revision = _required_identifier(raw.get("revision"), "revision")
        generation_raw = _required_mapping(raw.get("generation"), "generation")
        embeddings_raw = _required_mapping(raw.get("embeddings"), "embeddings")
        hardware_raw = _required_mapping(raw.get("hardware"), "hardware")
        return cls(
            name=name,
            revision=revision,
            generation=RoleSettings.from_dict("generation", generation_raw, revision),
            embeddings=RoleSettings.from_dict("embeddings", embeddings_raw, revision),
            hardware=HardwareSettings.from_dict(hardware_raw, policy),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "revision": self.revision,
            "generation": self.generation.to_dict(),
            "embeddings": self.embeddings.to_dict(),
            "hardware": self.hardware.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuntimeEndpoint:
    role: str
    kind: str
    model_id: str
    endpoint: EndpointConfig | None = None


@dataclass(frozen=True, slots=True)
class RuntimePlan:
    generation: RuntimeEndpoint
    embeddings: RuntimeEndpoint


class ProfileStore:
    """Persist the last activated inference profile."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "configuration" / "active-inference-profile.json"

    def active_profile(self, policy: RuntimePolicy | None = None) -> InferenceProfile | None:
        if not self.path.exists():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return InferenceProfile.from_dict(raw, policy or RuntimePolicy(str(raw.get("runtime_policy", "stored"))))

    def save_active(self, profile: InferenceProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


class InferenceSettingsManager:
    """Validate, activate and persist inference runtime profiles."""

    def __init__(
        self,
        store: ProfileStore,
        runtime_policy: RuntimePolicy,
        *,
        sidecar_launcher: Callable[[str, InferenceProfile], bool | None] | None = None,
        endpoint_probe: Callable[[str, EndpointConfig], EndpointProbeResult] | None = None,
    ):
        self.store = store
        self.runtime_policy = runtime_policy
        self.sidecar_launcher = sidecar_launcher or (lambda role, profile: True)
        self.endpoint_probe = endpoint_probe or (lambda role, endpoint: EndpointProbeResult(True, endpoint.base_url))

    def apply_profile(self, raw_profile: Mapping[str, Any]) -> InferenceProfile:
        profile = InferenceProfile.from_dict(raw_profile, self.runtime_policy)
        plan = self.runtime_plan(profile)
        self._activate(plan, profile)
        self.store.save_active(profile)
        return profile

    def runtime_plan(self, profile: InferenceProfile | None = None) -> RuntimePlan:
        selected = profile or self.store.active_profile(self.runtime_policy)
        if selected is None:
            raise InferenceSettingsError("PROFILE_MISSING", "no active inference profile has been selected")
        return RuntimePlan(
            generation=self._endpoint_for(selected.generation),
            embeddings=self._endpoint_for(selected.embeddings),
        )

    def _endpoint_for(self, role: RoleSettings) -> RuntimeEndpoint:
        return RuntimeEndpoint(role=role.role, kind=role.mode, model_id=role.model_id, endpoint=role.endpoint)

    def _activate(self, plan: RuntimePlan, profile: InferenceProfile) -> None:
        for endpoint in (plan.generation, plan.embeddings):
            if endpoint.kind == "external":
                assert endpoint.endpoint is not None
                probe = self.endpoint_probe(endpoint.role, endpoint.endpoint)
                if probe.redirect_target:
                    raise InferenceSettingsError("REDIRECT_FORBIDDEN", "external inference endpoint redirected to another destination")
                if not probe.ready:
                    raise InferenceSettingsError("ENDPOINT_UNAVAILABLE", "external inference endpoint did not become ready", retryable=True)
            else:
                result = self.sidecar_launcher(endpoint.role, profile)
                if result is False:
                    raise InferenceSettingsError("SIDECAR_UNAVAILABLE", "local inference sidecar did not become ready", retryable=True)


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InferenceSettingsError("INVALID_HARDWARE_SETTING", f"{field} must be a positive integer")
    return value


def _parse_tensor_split(raw: Any, split_mode: str) -> tuple[float, ...]:
    if raw in (None, ""):
        values: tuple[float, ...] = ()
    elif isinstance(raw, (str, bytes)):
        raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "tensor_split must be a numeric sequence")
    else:
        values = tuple(float(item) for item in raw)
    if not values:
        if split_mode == "tensor":
            raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "tensor split mode requires split proportions")
        return ()
    if len(values) < 2 or any(value <= 0 for value in values) or abs(sum(values) - 1.0) > 0.000001:
        raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "tensor_split must contain positive proportions summing to 1")
    if split_mode != "tensor":
        raise InferenceSettingsError("INVALID_HARDWARE_SETTING", "tensor_split is only valid with tensor split mode")
    return values


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InferenceSettingsError("INVALID_PROFILE", f"{field} must be an object")
    return value


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InferenceSettingsError("INVALID_PROFILE", f"{field} is required")
    return text


def _required_identifier(value: Any, field: str) -> str:
    text = _required_text(value, field)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-+")
    if any(char not in allowed for char in text):
        raise InferenceSettingsError("INVALID_PROFILE", f"{field} contains unsupported characters")
    return text
