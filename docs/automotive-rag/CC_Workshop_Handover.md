# CC Workshop implementation handover

Updated UTC: 2026-09-12T23:17:14Z

The project resumed from the Excel tracker and reconciled the newer GitHub branch state before making more changes. The current verified source commit is `933a39204a90ff60d26c96444de66dc379e31065` on branch `codex/cc-workshop-offline`.

## Current tracker

- Snapshot ID: `CC-SNAPSHOT-20260912231714290-fc76223c`
- Previous snapshot ID: `CC-SNAPSHOT-20260912180231622-e8a8cf42`
- Workbook schema version: `1.0.0`
- Plan version: `approved-d3e0ce2d7d20`
- Preserved original planning inputs still match their recorded hashes.
- The external `Downloads` template now differs from the original input hash and is intentionally left untouched.

## Current task state

- CC-T000, CC-T001 and CC-T002 remain complete.
- CC-T003 is in progress with S01-S03 done. Garage storage and request-scope implementation now has passing focused evidence, but S04 review remains open before task closure.
- CC-T009 is in progress with S01-S03 done. Provider conformance implementation now has passing focused evidence, but S04 review remains open before task closure.
- CC-T010, CC-T011 and CC-T012 remain in progress. Their focused synthetic fixtures pass, but real model files, loaded llama.cpp runtime, real hardware measurements and installer/runtime acceptance are not complete.
- CC-T025 remains gated on confirmed vehicle configuration and applicable original manual/source material.

## Source changes in 933a392

- Added Garage HTTP boundary routes and JSON-safe immutable record rendering.
- Kept private content routes tied to a confirmed VIN.
- Blocked legacy global library/query use until scoped Garage indexes are implemented.
- Disabled the unscoped manual-review blueprint by default in the main app.
- Preserved valid legacy absolute Garage paths under the configured data root while rejecting storage paths outside it.
- Revalidated Garage context inside the per-Garage SQLite transaction.
- Hardened the local OpenAI-compatible provider adapter around endpoint traversal, probes, JSON-schema validation, stream framing, response identity, cancellation, image decoding, request limits, strict JSON parsing and normalized transport errors.
- Hardened model asset import, llama sidecar startup and inference settings rollback with focused synthetic fixtures.

## Verification

Focused Garage/runtime-contract command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_garage_isolation.py tests/acceptance/test_garage_request_scope.py tests/acceptance/test_runtime_contracts.py --junitxml=../evidence/cc-t003-direct-fix-focused.xml
```

Observed result: `30 passed, 1 skipped, 24 subtests passed`.

Provider command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_provider_conformance.py --junitxml=../evidence/cc-t009-provider-focused-3.xml
```

Observed result: `32 passed, 72 subtests passed`.

Runtime/model/settings command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_model_assets.py tests/acceptance/test_sidecar_lifecycle.py tests/acceptance/test_inference_settings.py --junitxml=../evidence/cc-t010-t011-t012-runtime-focused.xml
```

Observed result: `29 passed, 12 subtests passed`.

Full suite command:

```powershell
.venv/Scripts/python.exe -m pytest -q --junitxml=../evidence/resume-direct-full-suite-20260912.xml
```

Observed result: `141 passed, 1 skipped, 108 subtests passed`.

Tracker validation passed for the generated workbook and JSON. The saved workbook has six tabs in order, four named tables, no cached formula errors, no legacy project content and matching Excel/JSON snapshot IDs.

## Evidence files

Primary local evidence files:

- `work/evidence/resume-direct-implementation-20260912.md`
- `work/evidence/cc-t003-direct-fix-focused.xml`
- `work/evidence/cc-t009-provider-focused-3.xml`
- `work/evidence/cc-t010-t011-t012-runtime-focused.xml`
- `work/evidence/resume-direct-full-suite-20260912.xml`
- `work/tracker-validation.json`
- `work/direct-tracker-build-20260912.log`

The repository docs copy these into `docs/automotive-rag/evidence/work/...` or `docs/automotive-rag/evidence/outputs/...` for GitHub.

## Known limits

- The skipped Garage link-escape test requires directory-link creation rights unavailable to this Windows account.
- No real GGUF model or projector was loaded.
- No real llama.cpp server inference request was completed.
- No clean Windows installer, LAN mode, backup/restore, manual ingestion pipeline or repair pilot has passed.
- No actual VIN, engine, transmission, brake PR code or applicable original manual source has been provided for the real repair pilot.

## Next action

Finish review evidence for CC-T003 and CC-T009, then continue to CC-T004 or CC-T005 according to tracker readiness. Keep CC-T010, CC-T011 and CC-T012 open until their real asset/runtime gates are satisfied or explicitly deferred.
