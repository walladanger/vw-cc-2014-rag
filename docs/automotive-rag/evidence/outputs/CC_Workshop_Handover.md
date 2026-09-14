# CC Workshop implementation handover

Updated UTC: 2026-09-14T12:03:41.144Z

The project resumed from the Excel tracker, fixed the CC-T003 and CC-T009 independent review findings, and regenerated the tracker. The current verified source commit is `1e87202a7ed8923e270090aa87f22a4947a68bcc` on branch `codex/cc-workshop-offline`.

## Current tracker

- Snapshot ID: `CC-SNAPSHOT-20260914120341144-0acc14d6`
- Previous snapshot ID: `CC-SNAPSHOT-20260914115438499-8f7e3a4a`
- Workbook schema version: `1.0.0`
- Plan version: `approved-d3e0ce2d7d20`
- Preserved original planning inputs still match their recorded hashes.
- The external `Downloads` template differs from the original input hash and remains untouched.
- Versioning rule `CC-D014` is answered: every compiled software edition must advance the version number, use the matching committed and pushed source, and record the version/build artifact evidence in the tracker.

## Current task state

- CC-T000, CC-T001, CC-T002, CC-T003 and CC-T009 are complete.
- CC-T003 closed after fixing active-Garage route mismatch, strict Garage JSON payload storage, VIN-preserving source redirects and related review findings.
- CC-T009 closed after fixing provider cancellation propagation, JSON-schema capability probing, whole-operation deadlines, stream terminal handling, event limits, malformed UTF-8 normalization and legacy profile migration.
- CC-T010, CC-T011 and CC-T012 remain in progress. Their synthetic fixtures have passed, but real model files, loaded llama.cpp runtime, real hardware measurements and installer/runtime acceptance remain unperformed.
- CC-T025 remains gated on confirmed vehicle configuration and applicable original manual/source material.

## Source changes in 1e87202

- Required record-route path VINs to match an active VIN supplied by header, query or body.
- Rejected non-finite Garage record payload values and non-string mapping keys before persistence.
- Preserved validated VINs when `/viewer` redirects to `/pdf`.
- Preserved cancellation and closed-client provider errors during capability probes.
- Required JSON-schema provider probes to return schema-valid output before caching support.
- Applied provider timeout limits across the full operation.
- Counted all streaming data events, treated `[DONE]` as terminal and rejected post-terminal stream content.
- Normalized malformed provider UTF-8 bytes to `ProviderError(INVALID_RESPONSE)`.
- Migrated legacy inference profiles that predate `runtime_policy`.

## Verification

Reviewer-fix focused command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_garage_isolation.py tests/acceptance/test_garage_request_scope.py tests/acceptance/test_runtime_contracts.py tests/test_provider_conformance.py tests/acceptance/test_inference_settings.py --junitxml=../evidence/reviewer-fixes-focused-20260914.xml
```

Observed result: `81 passed, 1 skipped, 104 subtests passed`.

Full suite command:

```powershell
.venv/Scripts/python.exe -m pytest -q --junitxml=../evidence/reviewer-fixes-full-suite-20260914.xml
```

Observed result: `150 passed, 1 skipped, 112 subtests passed`.

Tracker validation passed for the generated workbook and JSON. The saved workbook has six tabs in order, four named tables, no cached formula errors, no legacy project content and matching Excel/JSON snapshot IDs.

## Evidence files

Primary local evidence files:

- `work/evidence/reviewer-fixes-20260914.md`
- `work/evidence/reviewer-fixes-focused-20260914.xml`
- `work/evidence/reviewer-fixes-full-suite-20260914.xml`
- `work/cc-workshop/.superpowers/sdd/CC_Workshop_Implementation_Plan/t003-t009-review-20260914.md`
- `work/reviewer-fixes-tracker-validation-20260914.log`
- `work/reviewer-fixes-tracker-build-20260914.log`

The repository docs copy these into `docs/automotive-rag/evidence/work/...` or `docs/automotive-rag/evidence/outputs/...` for GitHub.

## Known limits

- The skipped Garage link-escape test requires directory-link creation rights unavailable to this Windows account.
- No real GGUF model or projector was loaded.
- No real llama.cpp server inference request was completed.
- No clean Windows installer, LAN mode, backup/restore, manual ingestion pipeline or repair pilot has passed.
- No actual VIN, engine, transmission, brake PR code or applicable original manual source has been provided for the real repair pilot.

## Next action

Proceed to CC-T004 vehicle profiles/applicability or CC-T005 canonical source/provenance. Keep CC-T010, CC-T011 and CC-T012 open until their real asset/runtime gates are satisfied or explicitly deferred. For any compiled software edition, bump the version number, commit and push the matching source, compile the artifact, and record version/build evidence in the tracker.
