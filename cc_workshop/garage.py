"""Vehicle Garage registry and scoped record storage."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from .contracts import VehicleContext, normalize_vin
from .operations.paths import UnsafePathError, initialize_data_root, resolve_within

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class GarageError(RuntimeError):
    """Base class for Garage storage failures."""


class GarageAlreadyExists(GarageError):
    """Raised when a Garage already exists for a VIN."""


class GarageNotFound(GarageError):
    """Raised when a Garage or scoped record cannot be found."""


class StaleVehicleContext(GarageError):
    """Raised when a request context no longer matches live Garage metadata."""


@dataclass(frozen=True, slots=True)
class Garage:
    vin: str
    display_name: str
    database_path: Path
    vector_root: Path
    profile_revision: int
    library_revision: str
    created_at: str


@dataclass(frozen=True, slots=True)
class GarageRecord:
    id: str
    kind: str
    payload: Mapping[str, Any]
    schema_version: int
    profile_revision: int
    library_revision: str
    created_at: str
    updated_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{label} must use lowercase letters, digits, underscores, or hyphens")
    return normalized


def _payload_from_json(value: str) -> dict[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("record payload must be a JSON object")
    return _tuples_for_json_arrays(payload)


def _tuples_for_json_arrays(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples_for_json_arrays(item) for item in value)
    if isinstance(value, dict):
        return MappingProxyType({key: _tuples_for_json_arrays(item) for key, item in value.items()})
    return value


def thaw_payload(value: Any) -> Any:
    """Return a JSON-serializable copy of an immutable Garage payload."""

    if isinstance(value, Mapping):
        return {key: thaw_payload(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_payload(item) for item in value]
    return value


def _record_from_row(row: sqlite3.Row) -> GarageRecord:
    return GarageRecord(
        id=row["id"],
        kind=row["kind"],
        payload=_payload_from_json(row["payload_json"]),
        schema_version=int(row["schema_version"]),
        profile_revision=int(row["profile_revision"]),
        library_revision=row["library_revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class GarageRegistry:
    """Persistent registry mapping one VIN to one isolated Garage root."""

    def __init__(self, root: Path):
        self.paths = initialize_data_root(Path(root))
        self.root = self.paths.root
        self._init_registry()

    def _connect_registry(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.registry_db)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_registry(self) -> None:
        with closing(self._connect_registry()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS garages (
                        vin TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        database_path TEXT NOT NULL,
                        vector_root TEXT NOT NULL,
                        profile_revision INTEGER NOT NULL,
                        library_revision TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

    def create(self, vin: str, *, display_name: str, request_id: str) -> Garage:
        normalized_vin = normalize_vin(vin)
        display = str(display_name or "").strip() or normalized_vin
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        garage_root = resolve_within(self.paths.garages, normalized_vin)
        database_path = resolve_within(garage_root, "garage.sqlite")
        vector_root = resolve_within(garage_root, "vectors")
        garage_root.mkdir(parents=True, exist_ok=True)
        for directory in ("originals", "derivatives", "vectors", "exports"):
            resolve_within(garage_root, directory).mkdir(parents=True, exist_ok=True)
        created_at = _utc_now()
        garage = Garage(
            vin=normalized_vin,
            display_name=display,
            database_path=database_path,
            vector_root=vector_root,
            profile_revision=1,
            library_revision="0",
            created_at=created_at,
        )
        self._init_garage_database(garage)
        try:
            with closing(self._connect_registry()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO garages (
                            vin, display_name, database_path, vector_root,
                            profile_revision, library_revision, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            garage.vin,
                            garage.display_name,
                            garage.database_path.relative_to(self.paths.root).as_posix(),
                            garage.vector_root.relative_to(self.paths.root).as_posix(),
                            garage.profile_revision,
                            garage.library_revision,
                            garage.created_at,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise GarageAlreadyExists(f"Garage already exists for VIN {normalized_vin}") from exc
        return garage

    def get(self, vin: str) -> Garage:
        normalized_vin = normalize_vin(vin)
        with closing(self._connect_registry()) as connection:
            row = connection.execute("SELECT * FROM garages WHERE vin = ?", (normalized_vin,)).fetchone()
        if row is None:
            raise GarageNotFound(f"Garage not found for VIN {normalized_vin}")
        database_path = self._stored_path(row["database_path"])
        vector_root = self._stored_path(row["vector_root"])
        garage = Garage(
            vin=row["vin"],
            display_name=row["display_name"],
            database_path=database_path,
            vector_root=vector_root,
            profile_revision=int(row["profile_revision"]),
            library_revision=row["library_revision"],
            created_at=row["created_at"],
        )
        if not garage.database_path.is_file() or not garage.vector_root.is_dir():
            raise GarageError(f"Garage storage is missing for VIN {normalized_vin}")
        with closing(sqlite3.connect(garage.database_path)) as connection:
            meta_vin = connection.execute("SELECT value FROM garage_meta WHERE key = 'vin'").fetchone()
        if meta_vin is None or meta_vin[0] != normalized_vin:
            raise GarageError("Garage database identity does not match its registry entry")
        return garage

    def _stored_path(self, value: str) -> Path:
        raw = Path(str(value))
        if raw.is_absolute():
            resolved = raw.resolve(strict=False)
            try:
                resolved.relative_to(self.paths.root)
            except ValueError as exc:
                raise UnsafePathError(f"path escapes storage root: {resolved}") from exc
            return resolved
        return resolve_within(self.paths.root, value)

    def context(self, vin: str, request_id: str) -> VehicleContext:
        garage = self.get(vin)
        live_profile_revision, live_library_revision = self._garage_revisions(garage)
        return VehicleContext(
            vin=garage.vin,
            profile_revision=live_profile_revision,
            library_revision=live_library_revision,
            approved_source_ids=self._approved_sources(garage),
            request_id=request_id,
        )

    def validate_context(self, context: VehicleContext) -> Garage:
        garage = self.get(context.vin)
        profile_revision, library_revision = self._garage_revisions(garage)
        if (
            context.profile_revision != profile_revision
            or context.library_revision != library_revision
            or context.approved_source_ids != self._approved_sources(garage)
        ):
            raise StaleVehicleContext(
                f"Vehicle context for {context.vin} is stale; refresh the active Garage context"
            )
        return garage

    def _garage_revisions(self, garage: Garage) -> tuple[int, str]:
        with closing(sqlite3.connect(garage.database_path)) as connection:
            rows = dict(connection.execute("SELECT key, value FROM garage_meta").fetchall())
        return int(rows.get("profile_revision", garage.profile_revision)), str(
            rows.get("library_revision", garage.library_revision)
        )

    def list(self) -> tuple[Garage, ...]:
        with closing(self._connect_registry()) as connection:
            vins = tuple(row[0] for row in connection.execute("SELECT vin FROM garages ORDER BY vin"))
        return tuple(self.get(vin) for vin in vins)

    def _approved_sources(self, garage: Garage) -> tuple[str, ...]:
        with closing(sqlite3.connect(garage.database_path)) as connection:
            return tuple(row[0] for row in connection.execute(
                "SELECT source_id FROM source_associations WHERE vin = ? ORDER BY source_id",
                (garage.vin,),
            ))

    def validate_context_connection(self, context: VehicleContext, connection: sqlite3.Connection) -> None:
        rows = dict(connection.execute("SELECT key, value FROM garage_meta").fetchall())
        sources = tuple(row[0] for row in connection.execute(
            "SELECT source_id FROM source_associations WHERE vin = ? ORDER BY source_id",
            (context.vin,),
        ))
        if (
            rows.get("vin") != context.vin
            or int(rows.get("profile_revision", 0)) != context.profile_revision
            or str(rows.get("library_revision", "")) != context.library_revision
            or sources != context.approved_source_ids
        ):
            raise StaleVehicleContext(
                f"Vehicle context for {context.vin} is stale; refresh the active Garage context"
            )

    def _init_garage_database(self, garage: Garage) -> None:
        with closing(sqlite3.connect(garage.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS garage_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS records (
                        vin TEXT NOT NULL,
                        id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        profile_revision INTEGER NOT NULL,
                        library_revision TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(vin, id)
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS records_kind_idx ON records(vin, kind)")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS source_associations (vin TEXT NOT NULL, source_id TEXT NOT NULL, PRIMARY KEY(vin, source_id))"
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO garage_meta(key, value) VALUES (?, ?)",
                    (
                        ("vin", garage.vin),
                        ("display_name", garage.display_name),
                        ("profile_revision", str(garage.profile_revision)),
                        ("library_revision", garage.library_revision),
                        ("created_at", garage.created_at),
                    ),
                )


class GarageRepository:
    def __init__(self, registry: GarageRegistry):
        self.registry = registry

    def open(self, context: VehicleContext) -> "ScopedGarageRepository":
        self.registry.validate_context(context)
        return ScopedGarageRepository(self.registry, context)


class ScopedGarageRepository:
    def __init__(self, registry: GarageRegistry, context: VehicleContext):
        self._registry = registry
        self._context = context

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        garage = self._registry.get(self._context.vin)
        connection = sqlite3.connect(garage.database_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._registry.validate_context_connection(self._context, connection)
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def put_record(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        record_id: str | None = None,
        schema_version: int = 1,
    ) -> GarageRecord:
        valid_kind = _validate_identifier(kind, "kind")
        if not isinstance(payload, dict):
            raise ValueError("record payload must be a dictionary")
        if schema_version < 1 or isinstance(schema_version, bool):
            raise ValueError("schema_version must be a positive integer")
        identifier = _validate_identifier(record_id or uuid.uuid4().hex, "record_id")
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now = _utc_now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO records (
                    vin, id, kind, payload_json, schema_version,
                    profile_revision, library_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vin, id) DO UPDATE SET
                    kind = excluded.kind,
                    payload_json = excluded.payload_json,
                    schema_version = excluded.schema_version,
                    profile_revision = excluded.profile_revision,
                    library_revision = excluded.library_revision,
                    updated_at = excluded.updated_at
                """,
                (
                    self._context.vin,
                    identifier,
                    valid_kind,
                    payload_json,
                    schema_version,
                    self._context.profile_revision,
                    self._context.library_revision,
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM records WHERE vin = ? AND id = ?", (self._context.vin, identifier)).fetchone()
        return _record_from_row(row)

    def get_record(self, record_id: str) -> GarageRecord:
        identifier = _validate_identifier(record_id, "record_id")
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM records WHERE vin = ? AND id = ?", (self._context.vin, identifier)).fetchone()
        if row is None:
            raise GarageNotFound(f"record not found: {identifier}")
        return _record_from_row(row)

    def list_records(self, kind: str | None = None) -> list[GarageRecord]:
        with self.connection() as connection:
            if kind is None:
                rows = connection.execute("SELECT * FROM records WHERE vin = ? ORDER BY created_at, id", (self._context.vin,)).fetchall()
            else:
                valid_kind = _validate_identifier(kind, "kind")
                rows = connection.execute(
                    "SELECT * FROM records WHERE vin = ? AND kind = ? ORDER BY created_at, id",
                    (self._context.vin, valid_kind),
                ).fetchall()
        return [_record_from_row(row) for row in rows]

    def delete_record(self, record_id: str) -> bool:
        identifier = _validate_identifier(record_id, "record_id")
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM records WHERE vin = ? AND id = ?", (self._context.vin, identifier))
        return cursor.rowcount > 0

    def associate_source(self, source_id: str) -> VehicleContext:
        source = _validate_identifier(source_id, "source_id")
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_associations(vin, source_id) VALUES (?, ?)",
                (self._context.vin, source),
            )
            sources = tuple(row[0] for row in connection.execute(
                "SELECT source_id FROM source_associations WHERE vin = ? ORDER BY source_id",
                (self._context.vin,),
            ))
            revision = hashlib.sha256("\n".join(sources).encode("utf-8")).hexdigest()
            connection.execute("UPDATE garage_meta SET value = ? WHERE key = 'library_revision'", (revision,))
        return self._registry.context(self._context.vin, self._context.request_id)
