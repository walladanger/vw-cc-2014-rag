# CC-T003 through CC-T011 Windows verification checkpoint

Updated UTC: 2026-09-11T21:05:00Z

Repository: walladanger/vw-cc-2014-rag
Branch: codex/cc-workshop-offline
Verified HEAD: 58795e4210e60794d1aff910a98994e5c9b223bc
Local checkout path reported by user: C:\CODING PROJECTS\vw-cc-2014-rag
Python: 3.12.10 virtual environment
pytest: 9.1.1

## User-observed setup

The user cloned the repository, checked out `codex/cc-workshop-offline`, installed Python 3.12, created `.venv`, installed `requirements.txt` and `requirements-dev.txt`, and confirmed the branch fast-forwarded to `58795e4`.

## Focused test results observed in chat

```text
python -m pytest -q tests/acceptance/test_garage_isolation.py
.uuuuu.uuuu..uus.. [100%]
6 passed, 1 skipped, 11 subtests passed in 0.59s

python -m pytest -q tests/test_provider_conformance.py
25 passed, 66 subtests passed in 1.16s

python -m pytest -q tests/acceptance/test_model_assets.py
4 passed, 2 subtests passed in 0.10s

python -m pytest -q tests/acceptance/test_sidecar_lifecycle.py
...... [100%]
6 passed in 0.18s
```

## Combined checkpoint observed in chat

```text
python -m pytest -q tests/acceptance/test_garage_isolation.py tests/test_provider_conformance.py tests/acceptance/test_model_assets.py tests/acceptance/test_sidecar_lifecycle.py
.uuuuu.uuuu..uus..uuuuuuuuu.uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu.....uuuu..uuu.....uuuu...uuuuuu..uuu......uuuu.uu. [ 78%]
......... [100%]
41 passed, 1 skipped, 79 subtests passed in 1.64s
```

## Completion boundary

This verifies the local Windows/Python acceptance fixtures for:

- CC-T003 Garage isolation.
- CC-T009 inference provider contract.
- CC-T010 model asset and hardware discovery contracts.
- CC-T011 llama.cpp sidecar lifecycle supervisor.

It does not verify a real llama.cpp binary launch, real GGUF model load, real vision projector, actual GPU split behavior, installer packaging, LAN access, manual ingestion, real repair procedure, or confirmed vehicle applicability. The sidecar lifecycle suite uses fake process, fake port, and fake readiness probes.

## Next eligible implementation task

CC-T012 — Add hardware controls and alternative local endpoints.
