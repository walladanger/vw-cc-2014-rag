# CC Workshop implementation handover

Updated UTC: 2026-09-11T21:05:00Z

The user resumed implementation work in Chat, verified the focused acceptance suites on a local Windows checkout, and requested save/commit/push plus updated tracker workbooks. Code and text evidence are saved on the `codex/cc-workshop-offline` branch. Binary Excel tracker copies are provided separately as downloadable artifacts from the chat session.

## Saved state

- CC-T000: tracker completed. Six tabs, 36 tasks, 144 steps and 161 acceptance requirements.
- CC-T001: baseline research completed against `646df53b3945e8444877480b3976ca3e8b46007b`.
- CC-T002: runtime foundations completed at `88934b493a27e67e77052fd064757278523b40be`.
- CC-T003: Garage storage boundary implemented and locally verified on Windows at the current checkpoint. This includes isolated per-VIN SQLite/vector roots, immutable `VehicleContext`, stale-context checks, scoped records, traversal rejection and data-root ownership locking.
- CC-T009: inference provider contract implemented and locally verified. This includes the local/private OpenAI-compatible transport boundary, model listing, capabilities, text/image request shaping, strict JSON output handling, embeddings, streaming, cancellation and sanitized provider errors.
- CC-T010: model asset and hardware discovery contracts implemented and locally verified. This includes offline model-kit validation, manifest identity, projector enforcement, hash/size checks, runtime-probe hardware inventory and conservative CPU/single-GPU/multiple-GPU profiles.
- CC-T011: llama.cpp sidecar lifecycle supervisor implemented and locally verified with fake process/port/readiness probes. This includes command construction, loopback binding, ownership registry, port-conflict handling, readiness/model-ID checks, crash recovery and shutdown policy behavior.
- CC-T012 is the next eligible code task.
- CC-T033 through CC-T035 remain deferred future work.

## Verification checkpoint

Local environment reported by the user:

- Windows PowerShell.
- Repository path: `C:\CODING PROJECTS\vw-cc-2014-rag`.
- Branch: `codex/cc-workshop-offline`.
- Python virtual environment: Python 3.12.10.
- pytest installed from `requirements-dev.txt`.
- Verified source revision before the combined run: `58795e4210e60794d1aff910a98994e5c9b223bc`.

Combined command observed in chat:

```powershell
python -m pytest -q tests/acceptance/test_garage_isolation.py tests/test_provider_conformance.py tests/acceptance/test_model_assets.py tests/acceptance/test_sidecar_lifecycle.py
```

Observed combined result:

```text
41 passed, 1 skipped, 79 subtests passed in 1.64s
```

Focused results were also observed in chat:

- Garage isolation: `6 passed, 1 skipped, 11 subtests passed`.
- Provider conformance: `25 passed, 66 subtests passed`.
- Model assets: `4 passed, 2 subtests passed`.
- Sidecar lifecycle: `6 passed`.

Evidence file: `docs/automotive-rag/evidence/work/CC-T003-T011-windows-verification-20260911.md`.

## Verification boundaries

The passing checkpoint is a focused acceptance checkpoint for CC-T003, CC-T009, CC-T010 and CC-T011. It is not a release certification.

The llama.cpp sidecar lifecycle suite verifies the supervisor behavior using fake process, fake port and fake readiness probes. It does not prove that a real `llama-server.exe` binary starts, loads a GGUF model, uses a projector, exercises GPU split behavior or produces a real completion.

No model weights, projector files, installer package, clean restore, LAN deployment, manual ingestion, confirmed vehicle profile, real repair procedure or release gate has passed in this checkpoint.

Actual VIN, engine, transmission, brake PR code and applicable original manual review are still required before the real repair pilot.

## GitHub checkpoint

Repository branch: `https://github.com/walladanger/vw-cc-2014-rag/tree/codex/cc-workshop-offline`

Recent implementation commits:

- `432d9d11c4d4a5fb0d7e2bef5eff7579f79a3fd2` — Implement local inference provider contract.
- `1b48f673e6e7053044bd259552c72fdc515c396d` — Implement model asset and hardware discovery contracts.
- `88329b44cb71921bdfdff0cb4ec089b529e934e6` — Implement llama sidecar lifecycle supervisor.
- `58795e4210e60794d1aff910a98994e5c9b223bc` — Close garage isolation SQLite fixture handle on Windows.
- `2abbdfe46233739c874002efa02ab4b7ad4b47d6` — Record Windows verification checkpoint for CC-T003 through CC-T011.

This handover update is committed after the evidence checkpoint. Binary workbooks are not embedded in this Markdown file.

Original local input files, user manuals, model weights, downloaded runtime binaries, virtual environments and caches are not included in this checkpoint.

## Resume

Before more feature coding, pull the branch and verify the current head. The next code task is CC-T012 — hardware controls and alternative local endpoints.

Start CC-T012 by adding focused acceptance tests for settings validation and rollback, then implement only the settings boundary. Do not begin CC-T013 scoped embeddings until CC-T012 has its own observed acceptance evidence.

Real llama.cpp smoke testing can run once an actual pinned `llama-server.exe`, required DLLs and at least one GGUF model are present. Vision testing additionally requires a matching projector file.
