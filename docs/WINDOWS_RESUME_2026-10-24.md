# Windows app resume — 24 October 2026

Branch: `codex/cc-workshop-windows-cleanup`, based on `main` at
`646df53b3945e8444877480b3976ca3e8b46007b`.

This is an isolated cleanup/packaging patch. The newer application work remains
on `codex/cc-workshop-offline` (`2a4bdfab8c8235484bbe6af690ccae70b66fb788`).
Do not treat these branches as interchangeable or overwrite the offline work.
Reconcile the authoritative workbook before promoting CC-T020 or CC-T029.
Tracker synchronization has not been performed; those tasks remain in progress.

## Changes

- Remove scanner-report parsing, scan analytics schemas, related tests, CLI flags,
  and documentation. Preserve the manual/guide Qdrant export and source ledger.
- Add a Windows runtime dependency set without the optional training/video stack.
- Fix first-launch logging and persistent user-data paths for packaged execution.
- Package the existing desktop shell with Inno Setup, shortcuts, and uninstall.
- Add a Windows build workflow that uploads the installer and portable directory.

## Actual validation

- `python -m unittest discover -s tests -v`: 51 passed on Linux/Python 3.11.
- `python specverify.py selftest`: 11/11 cases correct.
- Flask `/` test-client request: HTTP 200.
- Corpus-only export against a temporary synthetic manifest: passed.
- No remaining scanner-vendor references or deleted-module imports in text files.
- `git diff --check`: passed.
- Retrieval self-test could not run: no local processed `out` corpus is present.
- Windows compilation, installation, WebView2 launch, and real-manual RAG remain
  unverified until Windows CI and a user-machine check complete.

## Diagram recovery

The requested output is a literal illustrated repair sequence, one close-up
action panel per step. Preserve factory-manual page anchors and exact specs.
The existing PDF illustration extraction in `ingest_manual.py` and step chunking
in `ingest_guide.py` are reusable, but are not the requested complete renderer.

Search covered GitHub main, newer offline/backup branch trees, repository and
owner code search, saved project files, and earlier conversations. April repair
guide images were identified, but no reusable renderer implementation was found.
The July `vw_cc_procedural_generator.py` is an approximate Blender exterior-model
generator and must not be represented as the repair-diagram renderer.

Do not mark diagram integration complete. Recover the original source or obtain
an explicit decision to implement the missing renderer before claiming CC-T020.
