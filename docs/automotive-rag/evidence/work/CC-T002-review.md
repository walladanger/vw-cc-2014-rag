# CC-T002 independent review

Status: final scoped re-review completed on 2026-09-10. All three recorded findings are resolved; no remaining T002 blocker was found. The coordinator owns final integration and the producer gate. No app, test, dependency or workbook file was changed by this reviewer.

## Final scoped verdict

**Ready for the CC-T002 producer gate, subject to the coordinator's final verification.**

- R1 resolved: the real query handler catches expected retrieval availability failures and returns JSON HTTP 503 with `error=retrieval_unavailable`. The new route-level regression drives the actual Flask route and checks that result.
- R2 resolved: app setup resolves `DATA_ROOT = default_data_root()` and defaults OUT_DIR below that root. The Waitress entry point imports the app lazily from `main()`, so inspecting server configuration does not initialize application data. A subprocess regression imports the actual browser app under a fresh configured temporary root and checks the resulting OUT_DIR.
- R3 resolved: LocalEmbedder passes `local_files_only=True` to its existing model constructor. A regression checks the actual constructor arguments without requiring optional model packages or network access. Missing model assets remain unavailable; this does not claim model provisioning or the future embedding pipeline is complete.
- Test isolation resolved for the reported failure: the two direct app-import tests establish temporary writable roots themselves. The browser and desktop subprocess tests establish their own roots. No external CC_WORKSHOP_DATA_ROOT or legacy VW_RAG_OUT was needed for the independent focused rerun.

Independent final command, from the checkout, after removing CC_WORKSHOP_DATA_ROOT, VW_RAG_OUT and ENABLE_MANUAL_REVIEW from the child environment:

```text
.venv/Scripts/python.exe -B -m pytest tests/acceptance/test_runtime_contracts.py -q -p no:cacheprovider
```

Actual result: **exit 0; 17 passed, 13 subtests passed in 2.58 seconds**. The test run used no externally supplied writable data root. This reviewer did not rerun the full suite; the producer reports 67 passed plus 13 subtests and the coordinator performs independent final verification.

The additional persistent-Chroma regression uses an actual temporary collection with explicitly supplied vectors, then executes ChromaLibrary retrieval and verifies the incompatible vehicle is absent. It needs neither a model download nor a live inference service. Dependency-lock limitations remain accurately disclosed: Python 3.12.14 Windows development environment is verified, packaging-extra and Python 3.11 resolution are not claimed.

The earlier findings and reproduction evidence below are retained as the review history, not current unresolved defects.

Scope: `work/briefs/CC-T002.md`; changed app/desktop/server/retrieval files; new shared contracts and operations modules; runtime acceptance tests; dependency declarations and the resolved Windows/Python lock. Historical vehicle-global state and strict applicability changes belong to later tasks and are not treated as new T002 defects.

## Findings requiring correction before the T002 gate

### R1 — Expected retrieval failures escape the structured unavailable response [P2]

At `app.py:354`, `lib.retrieve(...)` runs outside the preceding try/except that handles `get_library()`. A local embedding backend can become unavailable after successful library loading, so a supported query path returns Flask's generic HTML 500 instead of a structured unavailable response.

Measured with the real Flask `/query` route, a valid query, a simulated already-loaded library and `urllib.error.URLError` raised by its retrieval operation:

```json
{
  "probe": "query_backend_unavailable",
  "status": 500,
  "content_type": "text/html; charset=utf-8",
  "is_json": false,
  "body_start": "<!doctype html>\n<html lang=en>\n<title>500 Internal Server Error</title>"
}
```

No network request was made. The simulation replaces only backend access; routing and response construction are the actual application code. Cover expected transport/backend-unavailable failures at retrieval, return the existing structured unavailable contract, and add a route-level regression. Preserve diagnostic visibility of unexpected programmer errors rather than describing every exception as a transient connection outage.

Acceptance affected: supported query backends return a valid response or structured unavailable state.

### R2 — Browser/server entry points still select writable state under the installation tree [P2]

`app.py:37` still defaults OUT_DIR to `BASE_DIR/out`. `web_server.py` imports `app` before its runtime configuration is loaded. `CC_WORKSHOP_DATA_ROOT` therefore moves desktop state but not direct browser/server state. On Windows, default manual-review registration immediately creates `<OUT_DIR>/.manual_review/corrections`; retrieval also writes `.embcache` beneath OUT_DIR.

Read-only import probe with manual review disabled to avoid writes, VW_RAG_OUT absent, and CC_WORKSHOP_DATA_ROOT explicitly configured:

```json
{
  "probe": "browser_data_root",
  "actual_app_out": ".../work/cc-workshop/out",
  "configured_root": ".../work/review-data-root-unused",
  "expected_under_configured_root": false
}
```

Use the shared runtime data-root selection before app setup for both launch paths, while preserving any deliberately supported explicit legacy path override. Add an isolated subprocess/import test for browser startup with a fresh writable data root, not just the existing desktop import test. The installation directory must not be required to be writable.

Implementation requirement affected: logs and writable state outside application installation paths.

### R3 — Legacy local embedder still permits implicit model retrieval [P2]

`retrieve.py:142–145` calls `SentenceTransformer("all-MiniLM-L6-v2")` without an offline-only constraint. The new core requirements omit sentence-transformers, so an unavailable response is legitimate when those optional dependencies are absent. However, users who install the optional ingestion dependencies or retain an existing environment can activate this constructor through the selected local runtime; it remains a named-model load with no explicit provisioning boundary.

An in-memory constructor spy captured the actual LocalEmbedder call, without importing a model package or contacting a network:

```json
{
  "probe": "legacy_local_model_constructor",
  "calls": [{"args": ["all-MiniLM-L6-v2"], "kwargs": {}}]
}
```

This establishes the absence of an offline constraint, not an observed download. Add a bounded guard that uses already-provisioned local assets only, and return unavailable when missing. Full versioned embedding/index replacement remains CC-T013; it is unnecessary to build that pipeline in T002.

Selected architecture affected: explicit provisioning operations, no implicit downloads during normal offline queries.

## Checks with no current finding

- Shared VehicleContext is frozen, copies its approved-source sequence to a tuple, normalizes VIN syntax and rejects boolean/fractional profile revisions.
- The Chroma retrieval signature now accepts `profile`, and both dense and lexical candidate filters forward it. Existing fail-open applicability semantics are an identified later-task concern, not silently claimed fixed by T002.
- Runtime configuration and server options default to `127.0.0.1`. Explicit host overrides remain explicit.
- Desktop data-root initialization precedes boot logging, fixing the missing logs-directory startup path.
- Core requirements exclude Whisper, yt-dlp, torch, transformers and sentence-transformers. Optional ingestion requirements hold those relevant ingestion dependencies.
- The lock header accurately states Windows x64/Python 3.12.14 development resolution and explicitly disclaims packaging-extra and Python 3.11 resolution.
- Independent installed-metadata comparison found all 94 locked package versions match the current virtual environment exactly. Python reports 3.12.14. pywebview and PyInstaller are not installed there, consistent with the lock's declared limitation.
- Packaging and native desktop startup have not been claimed verified by this reviewer. The existing import-only desktop test does not launch a real webview; that is acceptable for the T002 startup-path check but is not a Windows installer acceptance test.

## Test quality and final recheck

The existing Chroma regression exercises the real retrieve method with controlled dense and lexical dependencies. The data-root test exercises actual directory creation under a temporary root, and the desktop test imports the real launcher in a subprocess. These are useful behavior tests.

The acceptance suite lacks the two real route/startup-path cases identified above. It also checks only runtime dependency-name exclusion and a single cloud mode (`dual`); ensure any new offline constructor constraint and expected retrieval failure are covered explicitly. The final focused/full suites, source state and any changed line numbers must be rechecked after producer fixes.

This report is preliminary because source_setup is still editing. The coordinator should not interpret it as a final clean review or passed producer gate.

## Reproduction commands

Working directory: `work/cc-workshop`. Interpreter: `.venv/Scripts/python.exe`. Each probe was executed as an inline script with `-B -c`, so it did not create probe modules or bytecode. App manual-review registration was disabled for the read-only import.

Actual route, data-root and local-constructor probe:

```python
import os, json, urllib.error, sys, types
from unittest.mock import patch
os.environ['ENABLE_MANUAL_REVIEW'] = '0'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['CC_WORKSHOP_DATA_ROOT'] = r'C:\Users\Warwick\Documents\Codex\2026-09-10\using-the-three-attached-files-i\work\review-data-root-unused'
os.environ.pop('VW_RAG_OUT', None)
import app as app_module
from cc_workshop.operations.config import load_runtime_config

class UnavailableLibrary:
    def retrieve(self, *args, **kwargs):
        raise urllib.error.URLError('simulated local embedding backend unavailable')

app_module.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
with patch.object(app_module, '_library_unavailable', return_value=None), patch.object(app_module, 'get_library', return_value=UnavailableLibrary()):
    response = app_module.app.test_client().post('/query', json={'q': 'starter inspection'})
    print(response.status_code, response.content_type, response.is_json)

print(app_module.OUT_DIR, load_runtime_config().data_root)
import retrieve
calls = []
class CaptureTransformer:
    def __init__(self, *args, **kwargs):
        calls.append({'args': args, 'kwargs': kwargs})
with patch.dict(sys.modules, {'sentence_transformers': types.SimpleNamespace(SentenceTransformer=CaptureTransformer)}):
    retrieve.LocalEmbedder()
print(json.dumps(calls))
```

Lock provenance probe:

```python
import importlib.metadata as md, json, re, sys
from pathlib import Path
normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
installed = {normalize(d.metadata['Name']): d.version for d in md.distributions()}
lines = [s for s in Path('requirements-py312-win.lock').read_text().splitlines() if s and not s.startswith('#')]
mismatches = []
for line in lines:
    name, version = line.split('==', 1)
    actual = installed.get(normalize(name))
    if actual != version:
        mismatches.append({'name': name, 'locked': version, 'installed': actual})
print(json.dumps({'python': sys.version.split()[0], 'locked_packages': len(lines), 'mismatches': mismatches, 'desktop_extra_installed': 'pywebview' in installed, 'packaging_extra_installed': 'pyinstaller' in installed}))
```

Observed lock output:

```json
{"python":"3.12.14","locked_packages":94,"mismatches":[],"desktop_extra_installed":false,"packaging_extra_installed":false}
```
