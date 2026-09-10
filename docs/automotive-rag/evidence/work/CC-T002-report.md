# CC-T002 implementation report

## Result

Runtime contracts and baseline defect repairs are implemented for coordinator review. The public shared contract is `cc_workshop/contracts.py`; `VehicleContext` is frozen, validates a normalized 17-character VIN and positive integer revision, rejects malformed source-ID collections, and preserves approved source order in an immutable tuple.

Writable application defaults now resolve below `CC_WORKSHOP_DATA_ROOT` or `%LOCALAPPDATA%\CC Workshop`. Desktop logs and boot state are created there before logging begins. Browser and Waitress entry points default to `127.0.0.1`, with explicit environment overrides available.

The legacy Chroma retrieval method now accepts the same `profile` keyword as the in-memory implementations and applies vehicle filtering to lexical and vector candidates. The test suite exercises an actual persistent Chroma collection as well as the lightweight transport seam.

Required runtime selection rejects cloud embedding modes before backend activation. Local MiniLM loading uses `local_files_only=True`, so missing assets cannot trigger an implicit network download. Retrieval transport/runtime failures at `/query` return structured JSON HTTP 503 with `error=retrieval_unavailable`.

Dependencies are split into required runtime, optional ingestion/video, development, and packaging inputs. The required runtime retains offline PDF import/view/export packages and excludes Torch, Transformers, sentence-transformers, Whisper, and yt-dlp. `requirements-py312-win.lock` records the environment actually resolved on Windows x64 with Python 3.12.14.

## Test-first evidence

Initial RED evidence: `work/evidence/CC-T002-red-initial.log` (exit 1; missing package, signature, and dependency boundaries).

Review RED evidence: `work/evidence/CC-T002-red-review1.log` (exit 1; three reviewer regressions reproduced).

Independent isolation RED evidence: `work/evidence/CC-T002-red-isolation-review.log` (exit 1; 3 failed, 14 passed, 13 subtests). Tests now provide temporary writable roots and no longer depend on real user state.

Final focused command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\acceptance\test_runtime_contracts.py -q --junitxml=..\evidence\CC-T002-focused-isolated.xml
```

Exit 0: 17 passed, 13 subtests passed. Evidence: `work/evidence/CC-T002-focused-isolated.xml`.

Final full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=..\evidence\CC-T002-full-isolated.xml
```

Exit 0: 67 passed, 13 subtests passed. Evidence: `work/evidence/CC-T002-full-isolated.xml`.

Dependency integrity: `.venv\Scripts\python.exe -m pip check` exited 0 with `No broken requirements found.` Git diff whitespace validation exited 0; Git emitted only expected Windows line-ending notices.

## Files

- `cc_workshop/__init__.py`
- `cc_workshop/contracts.py`
- `cc_workshop/operations/__init__.py`
- `cc_workshop/operations/config.py`
- `cc_workshop/operations/paths.py`
- `tests/acceptance/__init__.py`
- `tests/acceptance/test_runtime_contracts.py`
- `retrieve.py`
- `app.py` (only library selection/default writable path, structured retrieval failure, and main bind)
- `desktop.py`
- `web_server.py`
- `requirements.txt`
- `requirements-ingest.txt`
- `requirements-desktop.txt`
- `requirements-dev.txt`
- `requirements-packaging.txt`
- `requirements-py312-win.lock`

## Deliberate omissions

- No Python 3.11 resolution is claimed; the only available tested interpreter is Python 3.12.14.
- Packaging extras are declared but are not included in the resolved lock because they were not resolved in this environment.
- Model files were not downloaded. The local MiniLM backend reports unavailable when assets are absent.
- Garage storage, source association, and applicability persistence begin only after the CC-T002 contract gate is accepted.
- No HTTP routes or templates were added.
