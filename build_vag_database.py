#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from vag_pipeline.common import json_dump, now_iso
from vag_pipeline.corpus import build_source_ledger, iter_corpus
from vag_pipeline.embeddings import OllamaEmbedder
from vag_pipeline.qdrant_export import export_points


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build portable manual-backed Qdrant data exports"
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE", "http://localhost:11434"))
    parser.add_argument("--model", default=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    ledger = build_source_ledger(args.corpus, args.output / "source_ledger.json")
    if args.no_embeddings:
        qdrant = {"status": "skipped", "reason": "--no-embeddings"}
    else:
        embedder = OllamaEmbedder(args.ollama_url, args.model)
        qdrant = export_points(
            iter_corpus(args.corpus),
            args.output,
            embedder,
            args.batch_size,
        )
    build_manifest = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "corpus": str(args.corpus),
        "source_count": ledger["source_count"],
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

