# Independent runtime-contract test attempt

Command from the isolated checkout:
`./.venv/Scripts/python.exe -m pytest -q tests/acceptance/test_runtime_contracts.py`

Observed exit code: 1.

Observed summary: `3 failed, 14 passed, 13 subtests passed in 4.22s`.

Failures:
- `RuntimePathTests.test_web_server_options_default_to_loopback`
- `RetrievalCompatibilityTests.test_application_rejects_cloud_embedding_mode_before_backend_activation`
- `RetrievalCompatibilityTests.test_query_returns_structured_unavailable_when_retrieval_backend_fails`

All three attempted the real app import without an isolated data-root fixture. Default manual-review registration tried to create `C:/Users/Warwick/AppData/Local/CC Workshop/out/.manual_review/corrections` and received `PermissionError: [WinError 5] Access is denied` from the workspace sandbox. No permission escalation was requested. The correct follow-up is to isolate test state in a temporary writable location; the actual installed application's AppData default remains appropriate.

This is a failed verification attempt, retained independently from a later fixed test run. It does not establish a product release failure or a successful engineering gate.
