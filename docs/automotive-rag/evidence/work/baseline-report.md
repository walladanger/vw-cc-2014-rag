# CC Workshop baseline report

Prepared: 2026-09-10

## Checkout

- Repository: `walladanger/vw-cc-2014-rag`
- Isolated checkout: `C:\Users\Warwick\Documents\Codex\2026-09-10\using-the-three-attached-files-i\work\cc-workshop`
- Branch: `codex/cc-workshop-offline`
- HEAD: `646df53b3945e8444877480b3976ca3e8b46007b`
- Working tree after preparation: clean
- Repository instructions: no `AGENTS.md` files were present

## Python environment

- Virtual environment: `C:\Users\Warwick\Documents\Codex\2026-09-10\using-the-three-attached-files-i\work\cc-workshop\.venv`
- Interpreter: `C:\Users\Warwick\Documents\Codex\2026-09-10\using-the-three-attached-files-i\work\cc-workshop\.venv\Scripts\python.exe`
- Interpreter version: Python 3.12.14
- Compatibility note: the repository README specifies Python 3.11 for development/building; baseline tests pass under the available bundled Python 3.12.14 runtime.

Installed core packages include Flask 3.1.3, ChromaDB 1.5.9, HTTPX 0.28.1, Pillow 12.3.0, Pydantic 2.13.5, PyMuPDF 1.28.2, pypdf 6.18.0, pytest 9.1.1, rank-bm25 0.2.2, ReportLab 5.0.1, and Waitress 3.0.2. Chroma's normal dependencies were installed. Torch, Transformers, sentence-transformers, Whisper, yt-dlp, and model assets were deliberately not installed.

Activate with:

```powershell
Set-Location 'C:\Users\Warwick\Documents\Codex\2026-09-10\using-the-three-attached-files-i\work\cc-workshop'
.\.venv\Scripts\Activate.ps1
```

Or invoke the interpreter directly without activation:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

## Baseline verification

- Core dependency import check: passed
- Unit suite: 50 tests passed, 0 failures, 0 errors
- Command: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Safety verification self-test: 11/11 cases passed
- Command: `.\.venv\Scripts\python.exe specverify.py selftest`
- Expected warning: PyMuPDF 1.28.2 reports that the `fitz` compatibility API is deprecated; this does not fail the suite.
- No Ollama-dependent retrieval self-test was run because no Ollama service or model assets were provisioned as part of checkout preparation.

## Local project instructions

The README identifies these normal workflows:

- Web app: `run_web.ps1`, then browse to `http://localhost:5000`.
- Required local services for generated answers: Ollama with `qwen3.6:latest` and `nomic-embed-text`.
- Local indexed manual data is expected in an `out` directory or via `VW_RAG_OUT`; manuals and indexes are not part of the repository.
- Source PDFs remain canonical and must not be overwritten or replaced by cleaned reading copies.
- Safety-critical values must remain verbatim and citation-backed; `specverify.py` is the safety gate.

## Scope boundary

This preparation changed only the ignored virtual environment inside the clone and this external baseline report. No application source, output deliverable, or tracker file was edited.
