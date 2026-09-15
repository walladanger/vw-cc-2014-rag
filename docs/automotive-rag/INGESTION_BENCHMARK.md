# CC Workshop manual-ingestion benchmark

This benchmark is the gate before bulk-ingesting the canonical VW CC manual corpus. It reads the source ZIP without modifying it and selects three deliberately difficult manuals:

- Brake System (`D3E8012ED5C`) — PR-code applicability, warnings, procedures, specifications, diagrams.
- 1.8L/2.0L chain-drive engine (`D3E80480D47`) — long procedures, tables, applicability, exploded views.
- Wiring diagrams (`K0059040021`) — page topology, legends, component locations, cross-page continuation.

## Pipelines

`existing-pymupdf` uses the repository's existing `ingest_manual.py` helpers when available. This keeps the current citation-first/page-anchored/diagram-aware parser as the baseline.

`docling` uses `docling.document_converter.DocumentConverter` and writes Markdown plus structured document JSON. Docling is a benchmark-only dependency for now; it does not replace the existing ingest path automatically.

The benchmark also creates external result slots for:

- `ragflow`
- `nemo-retriever`
- `nvidia-rag-blueprint`

These are intentionally adapter-based instead of hard-coding vendor APIs. RAGFlow and NVIDIA services can change deployment/API details independently of CC Workshop; the benchmark contract stays stable.

## Run

```powershell
python -m pip install -r requirements-benchmark.txt
python benchmark_ingestion.py "C:\Users\Warwick\Downloads\No Watermark VW CC-20260906T173757Z-1-001.zip" --out out\ingestion-benchmark
```

Fast local-only dry run without page rendering or external result slots:

```powershell
python benchmark_ingestion.py "C:\Users\Warwick\Downloads\No Watermark VW CC-20260906T173757Z-1-001.zip" --out out\ingestion-benchmark --no-render --no-external
```

## External benchmark jobs

A normal run writes:

`out/ingestion-benchmark/external-jobs.json`

It contains nine jobs: Brake, Engine, and Wiring for each of RAGFlow, NeMo Retriever, and NVIDIA RAG Blueprint. Every job includes the exact input PDF path, SHA-256, expected result path, required fields, and optional RAG-evaluation fields.

Run each system using its current supported deployment method, then write its normalized JSON result to:

```text
out/ingestion-benchmark/external-results/<role>/<pipeline>.json
```

Example:

```json
{
  "status": "ok",
  "source_sha256": "<exact hash from external-jobs.json>",
  "page_count": 124,
  "pages_with_text": 124,
  "diagram_pages": 80,
  "rendered_pages": 80,
  "page_anchored": true,
  "section_hierarchy": true,
  "warnings_detected": 15,
  "tables_detected": 7,
  "elapsed_seconds": 31.8,
  "rag_eval": {
    "context_precision": 0.0,
    "context_recall": 0.0,
    "faithfulness": 0.0,
    "answer_relevancy": 0.0,
    "citation_precision": 0.0
  }
}
```

The importer rejects a result whose `source_sha256` does not match the exact PDF used by the benchmark. This prevents accidental comparisons against old Drive copies or another revision of a manual.

Re-run the benchmark after external results are present. Their scores will then appear beside the existing parser and Docling in `benchmark-report.json`.

## NVIDIA RAG-Eval hook

The external result contract reserves a `rag_eval` object for retrieval/generation metrics. Use the same verified question set for every pipeline. At minimum, record context precision, context recall, faithfulness, answer relevancy, and citation precision when the evaluator supports them.

Do not create reference answers from model memory. Each benchmark question and expected citation must be verified against the canonical VW source page first.

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

The permanent pipeline may be hybrid: one system can provide layout/structured extraction while the existing page-render/provenance layer remains authoritative for diagrams and citations.

## Open WebUI

Open WebUI should remain a presentation/retrieval client at this stage. The canonical corpus, applicability metadata, source hashes, and page artifacts should stay in the CC Workshop backend so the UI can be changed or replaced without rebuilding the knowledge base.
