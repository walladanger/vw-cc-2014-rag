# CC Workshop Tracker Continuity

## Authority

`CC_Workshop_Planning_Tracker.xlsx` is the project conductor and authoritative execution-state record. It controls task/step state, dependencies, gates, evidence, handover, and next-action continuity. Chat history is not a substitute for the tracker.

The implementation plan defines intended behavior. The Excel tracker records execution state. Generated JSON/Markdown mirrors support continuity and review but do not override the workbook.

## Checkpoint rule

At every meaningful engineering, ingestion, benchmark, or release checkpoint:

1. Reconcile Tasks, Steps, Evidence, Decisions, and Handover in the tracker.
2. Preserve stable IDs; never reuse issued IDs.
3. Do not mark engineering work Done from research or benchmark preparation alone.
4. Record exact commit/source hashes and observed evidence.
5. Publish the current tracker checkpoint and a text-readable state mirror with the code checkpoint.

## Current RAG benchmark state — 2026-09-16

The three-manual ingestion benchmark is now part of project planning.

Benchmark corpus:
- Brake System — D3E8012ED5C — 124 pages
- 1.8L/2.0L Engine — D3E80480D47 — 390 pages
- Wiring Diagrams — K0059040021 — 1,359 pages

Systems being compared:
1. Existing CC Workshop / PyMuPDF parser
2. Docling
3. RAGFlow
4. NVIDIA NeMo Retriever
5. NVIDIA RAG Blueprint

State:
- Existing parser baseline: completed.
- Docling: pending execution.
- RAGFlow: benchmark adapter/checklist prepared; external run pending.
- NVIDIA NeMo Retriever: benchmark adapter/checklist prepared; external run pending.
- NVIDIA RAG Blueprint: benchmark adapter/checklist prepared; external run pending.
- Shared scoring contract and 9 external jobs are prepared.

Promotion gate:

**Do not bulk-ingest the full 48-PDF corpus until the three-manual benchmark has been reviewed and page provenance, warning preservation, table fidelity, diagram/wiring continuity, citation precision, and vehicle/engine applicability all pass.**

## Tracker checkpoint

Current updated workbook artifact: `CC_Workshop_Planning_Tracker_updated_20260916.xlsx`.

The workbook includes a dedicated `RAG Benchmark` tab and explicit GitHub/tracker continuity rules. The binary workbook should be committed into the repository as a normal Git binary when using a local Git/Codex environment capable of binary file commits.
