"""Confirmed vehicle profiles and source-applicability decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ApplicabilityResult, ApplicabilityState, VehicleContext
from .garage import GarageRecord, GarageRegistry, GarageRepository

_PROFILE_FIELDS = frozenset({
    "model_year", "make", "model", "engine_code", "transmission_code",
    "market", "brake_pr_codes",
})


@dataclass(frozen=True, slots=True)
class ConfirmedField:
    name: str
    value: Any
    evidence: Mapping[str, Any]
    confirmed_at: str


@dataclass(frozen=True, slots=True)
class VehicleProfile:
    vin: str
    revision: int
    fields: Mapping[str, ConfirmedField]


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().upper()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(sorted({_canonical(item) for item in value}))
    return value


def _source_revision(requirements: Mapping[str, Any]) -> str:
    encoded = json.dumps(requirements, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class VehicleProfileStore:
    """Store confirmed facts separately from untrusted identification drafts."""

    def __init__(self, registry: GarageRegistry, context: VehicleContext):
        self.registry = registry
        self.context = context
        self.repository = GarageRepository(registry).open(context)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.repository.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vehicle_profile_fields (
                    vin TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    profile_revision INTEGER NOT NULL,
                    PRIMARY KEY (vin, field_name)
                );
                CREATE TABLE IF NOT EXISTS vehicle_profile_history (
                    vin TEXT NOT NULL,
                    profile_revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (vin, profile_revision)
                );
                CREATE TABLE IF NOT EXISTS identification_drafts (
                    vin TEXT NOT NULL,
                    id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (vin, id)
                );
                """
            )

    def profile(self) -> VehicleProfile:
        with self.repository.connection() as connection:
            revision = int(connection.execute(
                "SELECT value FROM garage_meta WHERE key = 'profile_revision'"
            ).fetchone()[0])
            rows = connection.execute(
                """SELECT field_name, value_json, evidence_json, confirmed_at
                   FROM vehicle_profile_fields WHERE vin = ? ORDER BY field_name""",
                (self.context.vin,),
            ).fetchall()
        fields = {
            row["field_name"]: ConfirmedField(
                row["field_name"], json.loads(row["value_json"]),
                json.loads(row["evidence_json"]), row["confirmed_at"]
            )
            for row in rows
        }
        return VehicleProfile(self.context.vin, revision, fields)

    def confirm(self, field_name: str, value: Any, evidence: Mapping[str, Any]) -> VehicleContext:
        field = str(field_name or "").strip().lower()
        if field not in _PROFILE_FIELDS:
            raise ValueError(f"unsupported vehicle profile field: {field}")
        if value is None or value == "" or value == []:
            raise ValueError("confirmed value is required")
        if not isinstance(evidence, Mapping) or not evidence:
            raise ValueError("confirmation evidence is required")
        value_json = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        evidence_json = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.repository.connection() as connection:
            current = connection.execute(
                "SELECT value_json, evidence_json FROM vehicle_profile_fields WHERE vin = ? AND field_name = ?",
                (self.context.vin, field),
            ).fetchone()
            if current and current["value_json"] == value_json and current["evidence_json"] == evidence_json:
                return self.registry.context(self.context.vin, self.context.request_id)
            revision = self.context.profile_revision + 1
            connection.execute(
                """INSERT INTO vehicle_profile_fields
                   (vin, field_name, value_json, evidence_json, profile_revision)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(vin, field_name) DO UPDATE SET
                     value_json=excluded.value_json, evidence_json=excluded.evidence_json,
                     confirmed_at=CURRENT_TIMESTAMP, profile_revision=excluded.profile_revision""",
                (self.context.vin, field, value_json, evidence_json, revision),
            )
            connection.execute(
                "UPDATE garage_meta SET value = ? WHERE key = 'profile_revision'", (str(revision),)
            )
            rows = connection.execute(
                "SELECT field_name, value_json, evidence_json FROM vehicle_profile_fields WHERE vin = ? ORDER BY field_name",
                (self.context.vin,),
            ).fetchall()
            snapshot = {
                row["field_name"]: {
                    "value": json.loads(row["value_json"]),
                    "evidence": json.loads(row["evidence_json"]),
                } for row in rows
            }
            connection.execute(
                """INSERT INTO vehicle_profile_history(vin, profile_revision, snapshot_json)
                   VALUES (?, ?, ?)""",
                (self.context.vin, revision, json.dumps(snapshot, sort_keys=True, separators=(",", ":"))),
            )
        self.context = self.registry.context(self.context.vin, self.context.request_id)
        self.repository = GarageRepository(self.registry).open(self.context)
        return self.context

    def add_identification_draft(
        self, draft_id: str, description: str, evidence: Mapping[str, Any] | None = None
    ) -> None:
        identifier = str(draft_id or "").strip()
        text = str(description or "").strip()
        if not identifier or not text:
            raise ValueError("draft id and description are required")
        with self.repository.connection() as connection:
            connection.execute(
                """INSERT INTO identification_drafts(vin, id, description, evidence_json)
                   VALUES (?, ?, ?, ?)""",
                (self.context.vin, identifier, text, json.dumps(dict(evidence or {}), sort_keys=True)),
            )

    def evaluate(self, requirements: Mapping[str, Any]) -> ApplicabilityResult:
        if not isinstance(requirements, Mapping) or not requirements:
            return ApplicabilityResult(
                ApplicabilityState.UNKNOWN, ("source has no applicability metadata",),
                self.context.profile_revision, _source_revision(requirements or {}),
            )
        profile = self.profile()
        reasons: list[str] = []
        unknown: list[str] = []
        for raw_name, required in requirements.items():
            name = str(raw_name).strip().lower()
            confirmed = profile.fields.get(name)
            if confirmed is None:
                unknown.append(f"{name} is not confirmed")
                continue
            actual = _canonical(confirmed.value)
            expected = _canonical(required)
            if name == "brake_pr_codes":
                actual_set = set(actual if isinstance(actual, tuple) else (actual,))
                expected_set = set(expected if isinstance(expected, tuple) else (expected,))
                if not actual_set.intersection(expected_set):
                    reasons.append(f"{name} does not match")
            elif actual != expected:
                reasons.append(f"{name} does not match")
        revision = _source_revision(requirements)
        if reasons:
            return ApplicabilityResult(
                ApplicabilityState.CONFIRMED_MISMATCH, tuple(reasons),
                profile.revision, revision,
            )
        if unknown:
            return ApplicabilityResult(
                ApplicabilityState.UNKNOWN, tuple(unknown), profile.revision, revision
            )
        return ApplicabilityResult(
            ApplicabilityState.CONFIRMED_MATCH, (), profile.revision, revision
        )

    def approval_is_stale(self, record: GarageRecord) -> bool:
        return record.profile_revision != self.registry.context(
            self.context.vin, self.context.request_id
        ).profile_revision
