"""Immutable contracts shared across vehicle-scoped services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


_VIN_LENGTH = 17
_VIN_FORBIDDEN = frozenset("IOQ")


def normalize_vin(value: str) -> str:
    vin = str(value or "").strip().upper()
    if (
        len(vin) != _VIN_LENGTH
        or not vin.isascii()
        or not vin.isalnum()
        or any(character in _VIN_FORBIDDEN for character in vin)
    ):
        raise ValueError("VIN must be 17 ASCII letters/digits and cannot contain I, O, or Q")
    return vin


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("approved_source_ids must be an iterable of non-empty strings")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError("approved_source_ids must contain only strings")
        normalized = value.strip()
        if not normalized:
            raise ValueError("approved_source_ids cannot contain blank values")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class VehicleContext:
    vin: str
    profile_revision: int
    library_revision: str
    approved_source_ids: tuple[str, ...]
    request_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "vin", normalize_vin(self.vin))
        if (
            isinstance(self.profile_revision, bool)
            or not isinstance(self.profile_revision, int)
            or self.profile_revision < 1
        ):
            raise ValueError("profile_revision must be a positive integer")
        library_revision = str(self.library_revision or "").strip()
        request_id = str(self.request_id or "").strip()
        if not library_revision:
            raise ValueError("library_revision is required")
        if not request_id:
            raise ValueError("request_id is required")
        object.__setattr__(self, "library_revision", library_revision)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "approved_source_ids", _ordered_unique(self.approved_source_ids))


class ApplicabilityState(str, Enum):
    CONFIRMED_MATCH = "confirmed_match"
    CONFIRMED_MISMATCH = "confirmed_mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ApplicabilityResult:
    state: ApplicabilityState
    reasons: tuple[str, ...] = ()
    evaluated_profile_revision: int = 0
    evaluated_source_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True, slots=True)
class Unavailable:
    code: str
    message: str
    retryable: bool = False
