# CC-T003 / CC-T009 reviewer fixes

Observed at: 2026-09-14T12:02:34Z
Source commit: 1e87202a7ed8923e270090aa87f22a4947a68bcc
Branch: codex/cc-workshop-offline
Reviewer report: work/cc-workshop/.superpowers/sdd/CC_Workshop_Implementation_Plan/t003-t009-review-20260914.md

## Findings addressed

- Active Garage mismatch on record routes now returns scoped not-found behavior when a request carries a different active VIN than the route VIN.
- Garage record storage now rejects non-finite JSON numbers and non-string mapping keys before persistence.
- Provider capability probes now preserve cancellation and closed-client states instead of downgrading them to unknown.
- JSON-schema capability probing now requires a valid schema-conforming response before support is cached.
- Provider response decoding normalizes malformed UTF-8 to ProviderError(INVALID_RESPONSE).
- Streaming now treats [DONE] as terminal and counts all SSE data events against the stream event limit.
- Provider deadlines are applied across the whole operation instead of restarting independently for each awaited transport read.
- Existing inference profiles without runtime_policy now migrate to the supplied current runtime policy and are rewritten atomically.
- Source viewer redirects now preserve the validated VIN when opening the PDF route.

## Verification

Focused reviewer-fix command:

`	ext
.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_garage_isolation.py tests/acceptance/test_garage_request_scope.py tests/acceptance/test_runtime_contracts.py tests/test_provider_conformance.py tests/acceptance/test_inference_settings.py --junitxml=../evidence/reviewer-fixes-focused-20260914.xml
`

Observed result:

`	ext
81 passed, 1 skipped, 104 subtests passed in 8.77s
`

Full suite command:

`	ext
.venv/Scripts/python.exe -m pytest -q --junitxml=../evidence/reviewer-fixes-full-suite-20260914.xml
`

Observed result:

`	ext
150 passed, 1 skipped, 112 subtests passed in 11.94s
`

git diff --check was run after the patch and returned exit code 0. It printed only Windows line-ending warnings.

The skipped test remains the Windows directory-link escape fixture, which requires directory-link creation rights unavailable to this account. The traversal and absolute-path escape fixtures ran.
