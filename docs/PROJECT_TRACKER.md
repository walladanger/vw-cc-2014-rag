# VW CC Workshop RAG Project Tracker

_Last updated: 2026-09-15_

This file is the GitHub-readable mirror of the Excel planning tracker. The Excel workbook can still be kept as the higher-level planning artifact, but this Markdown file gives us clean diffs, branch review, and a simple source of truth inside the repo.

## Tracker storage policy

- Keep `CC_Workshop_Planning_Tracker.xlsx` as the editable workbook when working locally.
- Keep this `docs/PROJECT_TRACKER.md` file as the GitHub mirror for task status and next actions.
- Prefer updating the Markdown tracker in the same PR as code changes.
- If the Excel workbook is added to GitHub later, store it under `docs/tracker/CC_Workshop_Planning_Tracker.xlsx` or `planning/CC_Workshop_Planning_Tracker.xlsx`.
- Do not rely on the Excel binary alone for project state, because GitHub diffs cannot show meaningful row-level changes.

## Current repo status from review

| Area | Status | Evidence / notes |
|---|---:|---|
| Manual ingestion | Implemented | `ingest_manual.py` stamps `vehicle`, `engine`, `model_year`, `system`, page anchors, diagrams, and source hash. |
| Vehicle applicability | Mostly implemented | `applicability.py` validates vehicle stamp; `retrieve.py` has `applies_to_vehicle()`. |
| Retrieval grounding | Implemented | `retrieve.py` has hybrid retrieval, grounding gate, citation context, and citation checks. |
| App active vehicle profile | Implemented | `app.py` defaults to `2014 VW CC 2.0T TSI` / `CBFA` and sends `profile=VEHICLE_PROFILE` during query. |
| Chroma production path | Needs fix | `app.py` prefers `ChromaLibrary` when `out/chroma_db` exists, but `ChromaLibrary.retrieve()` does not currently accept or apply `profile`. |
| Tests | Partly covered | `tests/test_vehicle_applicability.py` covers core logic and ingest guards, but not the Chroma-specific path. |

## Task status

| ID | Task | Status | Decision |
|---|---|---:|---|
| CC-T004 | Add vehicle profiles and applicability decisions | Mostly done | Do not restart this task. Finish the Chroma gap only. |
| CC-T004-FIX | Wire active vehicle profile into `ChromaLibrary` | Next | Add `profile` argument, apply `applies_to_vehicle()` in Chroma filters, add tests. |
| CC-T006 | Manual ingestion scale-up | Blocked by CC-T004-FIX | Safe to resume after Chroma path is scoped. |
| CC-T007 | Diagram/wiring-heavy retrieval verification | Blocked by ingestion scale-up | Needs real manuals, diagrams, and citation checks. |

## CC-T004-FIX acceptance criteria

1. `ChromaLibrary._passes_filter()` accepts `profile=None`.
2. `ChromaLibrary.retrieve()` accepts `profile=None` in the same signature shape as `Library.retrieve()` and `DualLibrary.retrieve()`.
3. Chroma BM25 candidate filtering applies `applies_to_vehicle(chunk, profile)`.
4. Chroma dense candidate filtering applies the same profile rule.
5. A test proves `ChromaLibrary` no longer crashes when called with `profile=...`.
6. A test proves wrong-vehicle chunks are excluded through the Chroma filter path.
7. Existing `Library` and `DualLibrary` behavior stays unchanged.

## Suggested implementation patch

In `retrieve.py`, update `ChromaLibrary` like this:

```python
    def _passes_filter(self, c, manual_id, system, vehicle_kw, profile=None):
        if manual_id and c.get("manual_id") != manual_id:
            return False
        if system and (c.get("system") or "").lower() != system.lower():
            return False
        if vehicle_kw and vehicle_kw.lower() not in (c.get("vehicle") or "").lower():
            return False
        if profile and not applies_to_vehicle(c, profile):
            return False
        return True

    def retrieve(self, query, k=5, alpha=0.5, manual_id=None, system=None,
                 vehicle_kw=None, boost=False, profile=None):
```

Then pass `profile` into both `_passes_filter()` calls inside `ChromaLibrary.retrieve()`.

## Verification commands

```powershell
cd "C:\CODING PROJECTS\vw-cc-2014-rag"
python -m pytest -q tests/test_vehicle_applicability.py
python -m pytest -q tests/test_vag_pipeline.py tests/test_specverify_clearance.py
```

After the code patch, add or extend tests so the Chroma filter path is covered without requiring a real ChromaDB server.

## Next project step

Complete `CC-T004-FIX` first. Then resume ingestion planning for the full PDF set, with special handling for diagrams, wiring diagrams, page images, and manual applicability metadata.
