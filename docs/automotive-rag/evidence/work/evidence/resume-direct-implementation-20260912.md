# Resume direct implementation checkpoint

Observed UTC: 2026-09-12T23:12:39Z

The resumed implementation continued from the reconciled GitHub checkpoint `d9d94ed854198b9c0252dcfdaf3b5afccb06c217` on branch `codex/cc-workshop-offline`.

Source commit created:

`933a39204a90ff60d26c96444de66dc379e31065`

Implemented and verified changes:

- Added Garage HTTP boundary routes and JSON-safe immutable record rendering.
- Kept private content routes tied to a confirmed VIN and blocked legacy global library/query use until scoped Garage indexes are implemented.
- Disabled the unscoped manual-review blueprint by default in the main application.
- Preserved valid legacy absolute Garage paths under the configured data root while rejecting paths outside it.
- Revalidated Garage context inside the per-Garage SQLite transaction.
- Hardened the OpenAI-compatible provider adapter around endpoint path traversal, synthetic capability probes, local JSON-schema validation, stream framing, response identity, cancellation, image decoding, request limits, strict JSON parsing and normalized transport errors.
- Hardened model asset import, llama sidecar startup, and inference settings rollback using focused synthetic fixtures.

Verification commands:

- `.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_garage_isolation.py tests/acceptance/test_garage_request_scope.py tests/acceptance/test_runtime_contracts.py --junitxml=../evidence/cc-t003-direct-fix-focused.xml`
  - Result: 30 passed, 1 skipped, 24 subtests passed.
- `.venv/Scripts/python.exe -m pytest -q tests/test_provider_conformance.py --junitxml=../evidence/cc-t009-provider-focused-3.xml`
  - Result: 32 passed, 72 subtests passed.
- `.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_model_assets.py tests/acceptance/test_sidecar_lifecycle.py tests/acceptance/test_inference_settings.py --junitxml=../evidence/cc-t010-t011-t012-runtime-focused.xml`
  - Result: 29 passed, 12 subtests passed.
- `.venv/Scripts/python.exe -m pytest -q --junitxml=../evidence/resume-direct-full-suite-20260912.xml`
  - Result: 141 passed, 1 skipped, 108 subtests passed.
- `git diff --check`
  - Result: exit 0; only normal Windows LF-to-CRLF working-copy warnings appeared before cleanup.

Known limits:

- The skipped Garage link-escape test requires directory-link creation rights unavailable to this Windows account.
- T003 and T009 still require final review evidence before task closure.
- T010, T011 and T012 have stronger fixture coverage, but real model files, a loaded llama.cpp server, hardware measurements and installer/runtime acceptance remain unperformed.
- No applicable real vehicle configuration or original repair manual pilot source has been supplied for CC-T025.
