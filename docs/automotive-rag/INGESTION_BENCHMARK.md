# CC Workshop manual-ingestion benchmark

This benchmark is the gate before bulk-ingesting the canonical VW CC manual corpus. It reads the source ZIP without modifying it and selects three deliberately difficult manuals:

- Brake System (`D3E8012ED5C`) — PR-code applicability, warnings, procedures, specifications, diagrams.
- 1.8L/2.0L chain-drive engine (`D3E80480D47`) — long procedures, tables, applicability, exploded views.
- Wiring diagrams (`K0059040021`) — page topology, legends, component locations, cross-page continuation.

## Pipelines

`existing-pymupdf` uses the repository's existing `ingest_manual.py` helpers when available. This keeps the current citation-first/page-anchored/diagram-aware parser as the baseline.

`docling` uses `docling.document_converter.DocumentConverter` and writes Markdown plus structured document JSON. Docling is a benchmark-only dependency for now; it does not replace the existing ingest path automatically.

## Run

```powershell
python -m pip install -r requirements-benchmark.txt
python benchmark_ingestion.py "C:\Users\Warwick\Downloads\No Watermark VW CC-20260906T173757Z-1-001.zip" --out out\ingestion-benchmark
```

Fast dry run without page rendering:

```powershell
python benchmark_ingestion.py "C:\Users\Warwick\Downloads\No Watermark VW CC-20260906T173757Z-1-001.zip" --out out\ingestion-benchmark --no-render
```

## Output

`out/ingestion-benchmark/benchmark-report.json` contains source hashes and per-pipeline measurements for each manual. Baseline diagram pages are rendered under each manual's `existing-pymupdf/pages/` directory unless `--no-render` is used. Docling output is written under each manual's `docling/` directory.

The report measures text coverage, diagram/page-image preservation, source provenance, section structure, warning detection, table signals, runtime, and a simple screening quality score. The score is not the final acceptance decision.

## Promotion rule

Do not bulk-ingest the 48-PDF corpus just because one parser has the highest score. Before promotion, manually verify representative answers from all three manuals, especially:

1. brake PR-code applicability and safety warnings;
2. engine procedure ordering, torque/spec tables, and cross-references;
3. wiring topology, legends, component identifiers, and continuation pages;
4. page citations resolving to the exact source page;
5. no visual loss introduced by watermark removal or parsing.

The permanent pipeline may be hybrid: Docling can provide layout/structured extraction while the existing page-render/provenance layer remains authoritative for diagrams and citations.

## Open WebUI

Open WebUI should remain a presentation/retrieval client at this stage. The canonical corpus, applicability metadata, source hashes, and page artifacts should stay in the CC Workshop backend so the UI can be changed or replaced without rebuilding the knowledge base.
