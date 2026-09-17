#!/usr/bin/env python3
"""Run the CC Workshop three-manual ingestion benchmark without bulk ingesting the corpus."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cc_workshop.ingestion_benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark VW manual ingestion on brake, engine, and wiring PDFs")
    parser.add_argument("zip_path", help="Path to the canonical No Watermark VW CC ZIP")
    parser.add_argument("--out", default="out/ingestion-benchmark", help="Benchmark output directory")
    parser.add_argument("--no-docling", action="store_true", help="Skip the Docling comparison")
    parser.add_argument("--no-external", action="store_true", help="Skip RAGFlow, NeMo Retriever, and NVIDIA RAG Blueprint result slots")
    parser.add_argument(
        "--external-results",
        default=None,
        help="Directory containing <role>/<pipeline>.json external benchmark results; defaults to <out>/external-results",
    )
    parser.add_argument("--no-render", action="store_true", help="Do not render baseline diagram pages (faster dry run)")
    args = parser.parse_args()

    report = run_benchmark(
        Path(args.zip_path),
        Path(args.out),
        include_docling=not args.no_docling,
        render_baseline_diagrams=not args.no_render,
        include_external=not args.no_external,
        external_results_dir=Path(args.external_results) if args.external_results else None,
    )
    print(json.dumps({
        role: {
            p["pipeline"]: {
                "status": p["status"],
                "quality_score": p.get("quality_score"),
                "elapsed_seconds": p.get("elapsed_seconds"),
            }
            for p in target["pipelines"]
        }
        for role, target in report["targets"].items()
    }, indent=2))
    if report.get("external_job_manifest"):
        print(f"External jobs: {report['external_job_manifest']}")
    print(f"Full report: {Path(args.out) / 'benchmark-report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
