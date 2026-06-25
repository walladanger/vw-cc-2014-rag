from __future__ import annotations

import configparser
import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import clean_text, redact_vins, safe_vehicle_id, stable_id
from .corpus import CorpusRecord

TABLE_COLUMNS = {
    "vehicle_profiles": [
        "vehicle_id", "brand", "model", "model_year", "engine_code",
        "transmission_code", "source", "first_seen_at",
    ],
    "diagnostic_sessions": [
        "session_id", "vehicle_id", "started_at", "source", "tool_version",
        "system_count", "fault_count", "write_capability",
    ],
    "module_scans": [
        "session_id", "vehicle_id", "ecu_address", "module_name", "status",
        "fault_count", "sampled_at", "source",
    ],
    "fault_events": [
        "event_id", "session_id", "vehicle_id", "ecu_address", "module_name",
        "dtc_code", "dtc_status", "description", "occurred_at", "source",
    ],
    "measurement_samples": [
        "session_id", "vehicle_id", "ecu_address", "module_name",
        "measurement_key", "measurement_name", "raw_value", "numeric_value",
        "normalized_value", "unit", "sampled_at", "sampling_rate_hz", "source",
    ],
    "coding_snapshots": [
        "snapshot_id", "session_id", "vehicle_id", "ecu_address", "module_name",
        "coding_type", "coding_value", "captured_at", "source", "write_capability",
    ],
    "adaptation_snapshots": [
        "snapshot_id", "session_id", "vehicle_id", "ecu_address", "module_name",
        "channel", "channel_name", "raw_value", "numeric_value", "unit",
        "captured_at", "source", "write_capability",
    ],
}

FILENAME_DATE = re.compile(r"^(20\d{12})_")
SYSTEM_SECTION = re.compile(r"^\d{2}_SYSTEM$")


def _timestamp(path: Path) -> str:
    match = FILENAME_DATE.match(path.name)
    if match:
        value = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        return value.isoformat()
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _parser(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    parser.read_string(text)
    return parser


def _vehicle_values(section: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        count = int(section.get("Num", "0") or 0)
    except ValueError:
        count = 0
    for number in range(1, count + 1):
        title = clean_text(section.get(f"{number:02d}_Title")).lower()
        value = clean_text(section.get(f"{number:02d}_Value"))
        if title:
            values[title] = value
    return values


def parse_icarsoft_report(path: Path, vin_salt: str) -> tuple[dict[str, list[dict]], list[CorpusRecord]]:
    parser = _parser(path)
    timestamp = _timestamp(path)
    source = redact_vins(path.name)
    diag = parser["DIAG_PARAM"] if parser.has_section("DIAG_PARAM") else {}
    vehicle = parser["VEH_INFO"] if parser.has_section("VEH_INFO") else {}
    vehicle_values = _vehicle_values(vehicle)
    report = parser["DTC_REPORT"] if parser.has_section("DTC_REPORT") else {}
    vin = clean_text(diag.get("VIN") or vehicle_values.get("vin"))
    vehicle_id = safe_vehicle_id(vin, vin_salt)
    brand = vehicle_values.get("brand", "")
    year = vehicle_values.get("year", "")
    model = vehicle_values.get("model", "") or vehicle_values.get("vehicle", "")
    engine_code = vehicle_values.get("engine code", "") or vehicle_values.get("engine", "")
    transmission_code = (
        vehicle_values.get("transmission code", "")
        or vehicle_values.get("transmission", "")
    )
    session_id = stable_id("icarsoft-session", path.name, vehicle_id)
    tool_version = clean_text(
        parser.get("APP_PARAM", "Version", fallback="")
    )
    tables = {name: [] for name in TABLE_COLUMNS}
    tables["vehicle_profiles"].append(
        {
            "vehicle_id": vehicle_id,
            "brand": brand,
            "model": model,
            "model_year": year,
            "engine_code": engine_code,
            "transmission_code": transmission_code,
            "source": source,
            "first_seen_at": timestamp,
        }
    )
    tables["diagnostic_sessions"].append(
        {
            "session_id": session_id,
            "vehicle_id": vehicle_id,
            "started_at": timestamp,
            "source": source,
            "tool_version": tool_version,
            "system_count": report.get("SysNum", "0"),
            "fault_count": report.get("DtcCount", "0"),
            "write_capability": "disabled",
        }
    )
    catalog: list[CorpusRecord] = []
    for section_name in parser.sections():
        if not SYSTEM_SECTION.match(section_name):
            continue
        section = parser[section_name]
        module_name = clean_text(section.get("Name"))
        address_match = re.match(r"^([0-9A-F]{2})\s+", module_name, re.IGNORECASE)
        ecu_address = address_match.group(1).upper() if address_match else ""
        status = clean_text(section.get("Status"))
        fault_count = int(section.get("DtcNum", "0") or 0)
        tables["module_scans"].append(
            {
                "session_id": session_id,
                "vehicle_id": vehicle_id,
                "ecu_address": ecu_address,
                "module_name": module_name,
                "status": status,
                "fault_count": fault_count,
                "sampled_at": timestamp,
                "source": source,
            }
        )
        for number in range(1, fault_count + 1):
            prefix = f"{number:02d}_"
            code = clean_text(section.get(prefix + "Code"))
            dtc_status = clean_text(section.get(prefix + "Status"))
            description = redact_vins(clean_text(section.get(prefix + "Content")))
            event_id = stable_id(session_id, ecu_address, code, number)
            tables["fault_events"].append(
                {
                    "event_id": event_id,
                    "session_id": session_id,
                    "vehicle_id": vehicle_id,
                    "ecu_address": ecu_address,
                    "module_name": module_name,
                    "dtc_code": code,
                    "dtc_status": dtc_status,
                    "description": description,
                    "occurred_at": timestamp,
                    "source": source,
                }
            )
            text = f"{code} — {description}. Module: {module_name}. Status: {dtc_status}."
            catalog.append(
                CorpusRecord(
                    "vag_diagnostic_catalog",
                    stable_id("dtc-catalog", code, module_name, description),
                    text,
                    {
                        "schema_version": 1,
                        "record_type": "dtc_observation",
                        "source_tier": "vehicle_observation",
                        "dtc_code": code,
                        "ecu_address": ecu_address,
                        "module_name": module_name,
                        "description": description,
                        "status": dtc_status,
                        "vehicle_id": vehicle_id,
                        "session_id": session_id,
                        "observed_at": timestamp,
                        "source": source,
                        "text": text,
                        "write_capability": "disabled",
                    },
                )
            )
    return tables, catalog


def merge_tables(target: dict[str, list[dict]], incoming: dict[str, list[dict]]) -> None:
    for name, rows in incoming.items():
        target[name].extend(rows)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
