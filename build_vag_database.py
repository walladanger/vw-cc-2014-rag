#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from itertools import chain
from pathlib import Path

from vag_pipeline.analytics import export_analytics
from vag_pipeline.common import json_dump, now_iso, redact_vins
from vag_pipeline.corpus import build_source_ledger, iter_corpus
from vag_pipeline.diagnostics import TABLE_COLUMNS, merge_tables, parse_icarsoft_report
from vag_pipeline.embeddings import OllamaEmbedder
from vag_pipeline.qdrant_export import export_points


def diagnostic_inputs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    decoded = sorted(root.rglob("*_decoded.txt"))
    return decoded or sorted(root.rglob("*.log"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build portable Qdrant and HEX-ready VAG data exports"
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE", "http://localhost:11434"))
    parser.add_argument("--model", default=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--vin-salt", default=os.getenv("VAG_VIN_SALT", "local-vag-analytics"))
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    ledger = build_source_ledger(args.corpus, args.output / "source_ledger.json")
    tables = {name: [] for name in TABLE_COLUMNS}
    catalog = []
    diagnostic_errors = []
    diagnostic_files = diagnostic_inputs(args.diagnostics) if args.diagnostics else []
    seen_vehicle_ids = set()
    for path in diagnostic_files:
        try:
            parsed_tables, records = parse_icarsoft_report(path, args.vin_salt)
        except Exception as exc:
            diagnostic_errors.append(
                {
                    "source": redact_vins(path.name),
                    "error_type": type(exc).__name__,
                    "error": redact_vins(str(exc))[:1000],
                }
            )
            continue
        profiles = parsed_tables["vehicle_profiles"]
        parsed_tables["vehicle_profiles"] = [
            row for row in profiles if row["vehicle_id"] not in seen_vehicle_ids
        ]
        seen_vehicle_ids.update(row["vehicle_id"] for row in profiles)
        merge_tables(tables, parsed_tables)
        catalog.extend(records)
    analytics = export_analytics(args.output, tables)
    json_dump(args.output / "diagnostic_rejections.json", diagnostic_errors)

    if args.no_embeddings:
        qdrant = {"status": "skipped", "reason": "--no-embeddings"}
    else:
        embedder = OllamaEmbedder(args.ollama_url, args.model)
        qdrant = export_points(
            chain(iter_corpus(args.corpus), catalog),
            args.output,
            embedder,
            args.batch_size,
        )
    build_manifest = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "corpus": str(args.corpus),
        "diagnostics": str(args.diagnostics or ""),
        "source_count": ledger["source_count"],
        "diagnostic_file_count": len(diagnostic_files),
        "diagnostic_imported_count": len(diagnostic_files) - len(diagnostic_errors),
        "diagnostic_rejected_count": len(diagnostic_errors),
        "analytics": analytics,
        "qdrant": qdrant,
        "safety": {
            "ecu_writes": "disabled",
            "security_access": "disabled",
            "coding_writes": "disabled",
            "adaptation_writes": "disabled",
            "raw_vin_export": "disabled",
        },
    }
    json_dump(args.output / "build_manifest.json", build_manifest)
    print(json.dumps(build_manifest, indent=2))


if __name__ == "__main__":
    main()
