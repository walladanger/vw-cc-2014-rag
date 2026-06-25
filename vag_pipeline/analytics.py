from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import json_dump, now_iso
from .diagnostics import TABLE_COLUMNS, write_csv

SEMANTIC_MODEL = {
    "name": "VAG Diagnostic Analytics",
    "version": 1,
    "description": "Read-only Volkswagen/Audi diagnostic observations and manual metadata.",
    "safety_rules": [
        "Never describe an observed DTC as proof that a component has failed.",
        "Filter engine-specific specifications by engine code.",
        "Authoritative manuals outrank community guides.",
        "Coding and adaptation records are snapshots only; write operations are disabled.",
        "Raw VINs must not be displayed or stored.",
    ],
    "relationships": [
        "vehicle_profiles.vehicle_id = diagnostic_sessions.vehicle_id",
        "diagnostic_sessions.session_id = module_scans.session_id",
        "diagnostic_sessions.session_id = fault_events.session_id",
        "diagnostic_sessions.session_id = measurement_samples.session_id",
        "diagnostic_sessions.session_id = coding_snapshots.session_id",
        "diagnostic_sessions.session_id = adaptation_snapshots.session_id",
    ],
    "recommended_visuals": {
        "multi_sensor_timeline": {
            "table": "measurement_samples",
            "x": "sampled_at",
            "y": "normalized_value",
            "series": "measurement_name",
            "filters": ["vehicle_id", "session_id", "ecu_address", "unit"],
        },
        "requested_vs_actual": {
            "table": "measurement_samples",
            "x": "sampled_at",
            "y": "numeric_value",
            "series": "measurement_name",
        },
        "dtc_frequency": {
            "table": "fault_events",
            "category": "dtc_code",
            "metric": "count(*)",
            "filters": ["vehicle_id", "module_name", "occurred_at"],
        },
        "coding_comparison": {
            "table": "coding_snapshots",
            "category": "ecu_address",
            "series": "captured_at",
            "value": "coding_value",
        },
    },
    "glossary": {
        "DTC": "Diagnostic Trouble Code; an observation requiring manual-backed diagnosis.",
        "ECU address": "VAG control-module address such as 01 Engine or 03 Brakes.",
        "requested value": "The control module's target value.",
        "actual value": "The measured or calculated current value.",
        "long coding": "A module configuration snapshot represented as bytes or bits.",
        "adaptation": "A named or numbered module parameter snapshot.",
    },
}

POSTGRES_DDL = """-- Generated read-only analytics schema for HEX
CREATE SCHEMA IF NOT EXISTS vag_analytics;

CREATE TABLE IF NOT EXISTS vag_analytics.vehicle_profiles (
  vehicle_id text PRIMARY KEY, brand text, model text, model_year text,
  engine_code text, transmission_code text, source text, first_seen_at timestamptz
);
CREATE TABLE IF NOT EXISTS vag_analytics.diagnostic_sessions (
  session_id uuid PRIMARY KEY, vehicle_id text, started_at timestamptz, source text,
  tool_version text, system_count integer, fault_count integer,
  write_capability text CHECK (write_capability = 'disabled')
);
CREATE TABLE IF NOT EXISTS vag_analytics.module_scans (
  session_id uuid, vehicle_id text, ecu_address text, module_name text, status text,
  fault_count integer, sampled_at timestamptz, source text
);
CREATE TABLE IF NOT EXISTS vag_analytics.fault_events (
  event_id uuid PRIMARY KEY, session_id uuid, vehicle_id text, ecu_address text,
  module_name text, dtc_code text, dtc_status text, description text,
  occurred_at timestamptz, source text
);
CREATE TABLE IF NOT EXISTS vag_analytics.measurement_samples (
  session_id uuid, vehicle_id text, ecu_address text, module_name text,
  measurement_key text, measurement_name text, raw_value text,
  numeric_value double precision, normalized_value double precision, unit text,
  sampled_at timestamptz, sampling_rate_hz double precision, source text
);
CREATE TABLE IF NOT EXISTS vag_analytics.coding_snapshots (
  snapshot_id uuid PRIMARY KEY, session_id uuid, vehicle_id text, ecu_address text,
  module_name text, coding_type text, coding_value text, captured_at timestamptz,
  source text, write_capability text CHECK (write_capability = 'disabled')
);
CREATE TABLE IF NOT EXISTS vag_analytics.adaptation_snapshots (
  snapshot_id uuid PRIMARY KEY, session_id uuid, vehicle_id text, ecu_address text,
  module_name text, channel text, channel_name text, raw_value text,
  numeric_value double precision, unit text, captured_at timestamptz, source text,
  write_capability text CHECK (write_capability = 'disabled')
);
CREATE INDEX IF NOT EXISTS fault_events_lookup
  ON vag_analytics.fault_events(vehicle_id, dtc_code, occurred_at);
CREATE INDEX IF NOT EXISTS measurement_samples_timeline
  ON vag_analytics.measurement_samples(session_id, measurement_key, sampled_at);
"""


def _write_parquet(path: Path, rows: list[dict], columns: list[str]) -> str:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return "pyarrow unavailable"
    normalized = [{column: row.get(column) for column in columns} for row in rows]
    if normalized:
        table = pa.Table.from_pylist(normalized)
    else:
        table = pa.table({column: pa.array([], type=pa.string()) for column in columns})
    pq.write_table(table, path, compression="zstd")
    return "written"


def export_analytics(root: Path, tables: dict[str, list[dict]]) -> dict[str, Any]:
    analytics_dir = root / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"generated_at": now_iso(), "tables": {}}
    for table_name, columns in TABLE_COLUMNS.items():
        rows = tables.get(table_name, [])
        csv_path = analytics_dir / f"{table_name}.csv"
        write_csv(csv_path, columns, rows)
        parquet_status = _write_parquet(
            analytics_dir / f"{table_name}.parquet", rows, columns
        )
        summary["tables"][table_name] = {
            "rows": len(rows),
            "csv": csv_path.name,
            "parquet": parquet_status,
        }
    (analytics_dir / "postgres_schema.sql").write_text(POSTGRES_DDL, encoding="utf-8")
    json_dump(analytics_dir / "hex_semantic_model.json", SEMANTIC_MODEL)
    json_dump(analytics_dir / "manifest.json", summary)
    return summary
