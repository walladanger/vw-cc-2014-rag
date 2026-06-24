# VW CC 2014 RAG Mechanic Assistant — Claude Code Handover
**Date:** June 2026  
**Vehicle:** 2014 VW CC 2.0T TSI, DSG (DQ250/02E)  
**Phase 1 (PDF cleaning): COMPLETE. Phase 2 (RAG pipeline): PARTIALLY BUILT. Phase 2B (video ingestion): PIPELINE READY. Phase 3 (generation + UI): NOT STARTED.**

---

## How to open a new Claude Code session

Paste this file as your first message in a new Claude Code chat. Opening line:

> *"I'm continuing the VW CC 2014 manual-backed RAG mechanic assistant. This handover covers everything built so far. Start with Phase 2 — ingest the remaining manuals using the originals, then build the generation layer."*

Upload alongside this file:
- `ingest_manual.py`, `retrieve.py`, `specverify.py`, `eval_ranking.py`
- `library_index.json` (current index — 8 manuals, 6 361 chunks)
- The original (watermarked) PDFs you want to ingest next

---

## The core rule — never drift from this

> **No manual citation, no technical answer.**

If the retrieval pipeline cannot find a grounded chunk from a factory PDF, the assistant refuses. Every number in a generated answer must be copied verbatim from a cited chunk and pass `specverify.verify_answer()`. There are no exceptions.

---

## What exists right now

### Scripts (download `vw_rag_phase2b.zip`)

| File | Purpose |
|------|---------|
| `ingest_manual.py` | PDF → page-anchored chunks + markdown + diagram images |
| `retrieve.py` | Hybrid BM25 + dense retrieval + grounding gate (manual tier) |
| `specverify.py` | Safety layer — torque spec extraction + answer verification |
| `eval_ranking.py` | Ranking quality harness (baseline 1.00/1.00 on current eval set) |
| `dewatermark_pdf.py` | Reading-copy utility (NOT part of RAG pipeline) |
| `ingest_video.py` | **NEW** — Whisper transcription + topic chunking + conflict detection for repair videos |
| `retrieve_video.py` | **NEW** — Hybrid BM25 + dense retrieval over video chunks (community tier) |
| `library_index.json` | Source-of-truth index — 8 manuals, 6 361 chunks, dedup by source_hash |
| `HANDOFF.md` | Deep technical notes (rawdict gotcha, numpy trick, chunk-splitting, etc.) |
| `RETRIEVAL_README.md` | Retrieval system docs and gate tuning notes |
| `SAFETY_ARCHITECTURE.md` | Safety layer design |

### Manuals already ingested (do NOT re-ingest these)

| manual_id | Title |
|-----------|-------|
| vw_passat_cc_maint_2023 | Maintenance Procedures |
| vw_cc_electrical_2018 | Electrical / Wiring |
| vw_ea888_18_20_repair | Engine Mechanical 1.8/2.0 TSI |
| vw_cc_2014_qsb | Quick Reference Spec Book |
| vw_cc_brakes_2011 | Brakes (9 stretch bolts flagged) |
| vw_cc_2014_body_qsb | Body QSB |
| vw_ac_r1234yf_servicing | A/C R1234yf |
| vw_09m_auto_trans_2019 | 6-speed Auto 09M (see open decisions below) |

### Clean PDFs (reading copies — human use only)

32 de-watermarked PDFs live in `VW_CC_2014_all_manuals_clean.zip` (330 MB) and the group zips. **These are NOT for ingestion.** They have different `source_hash` values than the originals. Ingesting them would create phantom citation targets that don't match the canonical source files.

The `ingest_manual.py` pipeline already strips the watermark during ingestion — always feed it the **original watermarked PDFs**.

---

## Phase 2 — Ingest remaining manuals (your first task)

~24 manuals still need ingesting. `library_index.json` deduplicates by `source_hash`, so running ingest on an already-indexed file is safe — it will skip cleanly.

### Workflow per manual

```bash
# 1. Inspect first — check page count, OCR needs, diagram pages
python ingest_manual.py inspect <original.pdf>

# 2. Ingest
python ingest_manual.py ingest <original.pdf> \
  --manual-id <id> \
  --title "<Human-readable title>" \
  --vehicle "2014 VW CC 2.0T TSI" \
  --system "<system e.g. HVAC / Body / Brakes>" \
  --out ./out

# 3. ALWAYS audit torque extraction after a new manual
python specverify.py audit
```

### Special handling: DTC chart QSB

The DTC chart manual has a cross-contamination safety bug if ingested naively. The same fault code (e.g. misfire rate threshold) has **different numeric values** for CBFA vs CCTA vs CNNA engines. Each chunk MUST be tagged with an `ENGINE_CODE` qualifier before ingestion. Do not ingest this manual without implementing that qualifier — wrong DTC thresholds are a diagnostic safety issue.

---

## Phase 2B — Ingest repair videos

The video pipeline is fully built. Use it in parallel with or after Phase 2 manual ingestion.

### Safety tier rules — hard contract

| Query type | Allowed source |
|---|---|
| Torque values, clearances, fluid specs | **Manual ONLY** — specverify enforces this |
| Stretch bolt / replace flags | **Manual ONLY** |
| Procedure step order | Manual primary; video as supplementary "see also" |
| Visual identification ("where is X") | Video OK as primary |
| Tips, gotchas, common mistakes | Video OK as primary |
| DTC thresholds | **Manual ONLY** — engine-code qualified |

**If a video value conflicts with the manual value, surface the conflict — never silently resolve it in the video's favour.**

### Install dependencies

```bash
pip install openai-whisper yt-dlp rank-bm25
# ffmpeg must be on PATH (yt-dlp uses it for audio extraction)
# Windows: winget install ffmpeg   OR   choco install ffmpeg
```

### Whisper model choice

| Model | Accuracy | VRAM / RAM | Notes |
|---|---|---|---|
| `medium` | Good | ~5 GB RAM (CPU) | Default — works on CPU |
| `large-v3` | Best | ~6 GB VRAM | Use if you have a GPU on TrueNAS |

### Ingest a single video

```bash
# Inspect first (no files written, just shows chunks preview)
python ingest_video.py inspect "https://youtube.com/watch?v=..." --whisper-model medium

# Ingest from YouTube URL
python ingest_video.py ingest "https://youtube.com/watch?v=..." \
  --video-id dsg_fluid_change_01 \
  --title "VW CC DSG DQ250 Fluid Change Full Walk-through" \
  --channel "EuroWrench" \
  --vehicle "2014 VW CC 2.0T TSI DSG" \
  --system "DSG/DQ250" \
  --out ./out

# Ingest from local file (user already has the videos)
python ingest_video.py ingest "/path/to/video.mp4" \
  --video-id dsg_filter_01 \
  --title "DSG Filter and Fluid Change" \
  --channel "EuroWrench" \
  --vehicle "2014 VW CC 2.0T TSI DSG" \
  --system "DSG/DQ250" \
  --out ./out
```

### Batch ingest (for many videos at once)

Create `videos.txt` — one JSON object per line:
```json
{"source": "/videos/dsg_fluid.mp4", "video_id": "dsg_fluid_01", "title": "DSG Fluid Change", "channel": "EuroWrench", "vehicle": "2014 VW CC 2.0T TSI DSG", "system": "DSG/DQ250"}
{"source": "/videos/engine_mount.mp4", "video_id": "eng_mount_01", "title": "Engine Mount Replacement", "channel": "EuroWrench", "vehicle": "2014 VW CC 2.0T TSI", "system": "Engine"}
```

```bash
python ingest_video.py ingest-batch videos.txt --out ./out --whisper-model medium
```

### After ingestion

```bash
# List all ingested videos
python ingest_video.py list-videos --out ./out

# Review spec conflicts (torque values found in video transcripts — must cross-check)
python ingest_video.py conflicts --out ./out

# Test video retrieval
python retrieve_video.py "DSG fluid change steps" -k 5 --out ./out

# Selftest the video index
python retrieve_video.py --selftest --out ./out
```

### What videos.txt should contain for Warwick's videos

Per video, the user needs to provide:
- `source` — local file path (since user has files already, not URLs)
- `video_id` — short snake_case identifier (e.g. `dsg_service_01`)
- `title` — descriptive title
- `channel` — who made the video
- `vehicle` — confirm it applies to 2014 VW CC 2.0T TSI (not generic Golf etc.)
- `system` — which car system (DSG/DQ250, Engine, Brakes, HVAC, Suspension, etc.)

Vehicle confirmation is important — a video for a Golf 2.0T may have different torque specs even for the same engine code.

---

## Phase 3 — Generation layer (build this next after ingestion)

### Architecture (with video tier)

```
User query
    │
    ├──► retrieve.py          ──► manual chunks (CANONICAL tier)   ─┐
    │                                                                 ├──► assemble_context()
    └──► retrieve_video.py    ──► video chunks (COMMUNITY tier)    ─┘
                                                                      │
                                                                      ▼
                                                          Ollama (Qwen 3 14B)
                                                          [manual specs verbatim]
                                                          [video as "see also"]
                                                                      │
                                                                      ▼
                                                          specverify.verify_answer()
                                                          [checks manual citations ONLY]
                                                                      │
                                                                      ▼
                                                          Return answer
                                                          + manual page links → /viewer?manual={id}&page={n}
                                                          + video timestamps → YouTube URL at t=seconds
                                                          + conflict warnings (if video ≠ manual)
```

Use `assemble_context()` from `retrieve_video.py` to build the combined context block.

### Ollama connection

```python
OLLAMA_BASE = "http://localhost:11434"   # user's TrueNAS box

# Generate
import httpx, json

def generate(prompt: str, context: str) -> str:
    payload = {
        "model": "qwen3:14b",           # recommended — good instruction-following
        "prompt": SYSTEM_PROMPT + "\n\nCONTEXT:\n" + context + "\n\nQUESTION: " + prompt,
        "stream": False,
    }
    r = httpx.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=120)
    return r.json()["response"]
```

### System prompt (critical — read carefully before changing)

```
You are a factory-manual mechanic assistant for a 2014 VW CC 2.0T TSI.
You receive two types of context: FACTORY MANUAL (canonical) and COMMUNITY VIDEO (supplementary).

Rules you must never break:
1. Every torque value, clearance, fluid capacity, or part number you state must be
   copied CHARACTER-FOR-CHARACTER from the FACTORY MANUAL section of the CONTEXT.
   Do not use numbers from VIDEO sections as specs. Do not round, convert, or paraphrase.
2. Cite every manual fact as [Manual: {manual_id}, Page {physical_page}].
3. Cite every video reference as [Video: "{title}", ~{timestamp}].
4. If the answer is not supported by the FACTORY MANUAL section, say:
   "I cannot find this in the factory manuals I have indexed. Check the source PDF directly."
   You may still mention a related video procedure as context, but never as the spec source.
5. If a fastener is marked "Replace" or "Stretch bolt — replace after removal",
   reproduce that warning verbatim. Never omit it.
6. Angle-tightening stages must be reproduced in full: e.g. "40 Nm + 180°" not "40 Nm".
7. If a VIDEO section mentions a numeric value and it differs from the manual, output:
   "⚠ Note: video mentions [X Nm] but factory manual specifies [Y Nm] — always follow the manual."
```

### verify_answer() — not optional

```python
from specverify import verify_answer

answer, citations = generate_with_citations(query, context, allow_list)
ok, failures = verify_answer(answer, citations, chunks_by_id)
if not ok:
    # Do NOT return the answer — log failures and return a refusal
    return "I found relevant information but could not verify all specs. Check source PDF."
```

---

## Phase 4 — PDF viewer route

The citation `[Manual: vw_cc_brakes_2011, Page 47]` must be a clickable link that opens the factory PDF at that page. This is the human verification step — the user confirms the spec in the original document before acting on it.

```
GET /viewer?manual=vw_cc_brakes_2011&page=47
```

Implementation options (simplest first):
1. **Flask route** that calls `subprocess.run(["start", original_pdf_path, f"/A page={page}"])` on Windows
2. **Browser link** `file:///path/to/original.pdf#page=47` (works in Chrome/Edge)
3. **Embedded PDF viewer** (pdf.js) served locally

The `library_index.json` maps `manual_id` → `source_path` (the original PDF file path on disk). Use that mapping.

---

## Remaining open items (must resolve before going live)

### 1. DSG vs 09M confirmation (BLOCKING)

The user's CC has a **DSG (DQ250 / 02E)**. The currently-ingested transmission manual (`vw_09m_auto_trans_2019`) covers the **Aisin 09M 6-speed automatic** — a different gearbox.

**Action required:** Confirm whether the 09M is relevant (it's not, unless the car has been swapped), or source the correct DQ250/02E DSG manual and ingest that instead. Using wrong transmission specs is a safety issue.

### 2. Embedder calibration for production

Current retrieval floors are calibrated for **MiniLM-L6-v2 (384d)**. Once on the TrueNAS Ollama box, switch to `nomic-embed-text` (768d) and re-calibrate:

```bash
python retrieve.py --selftest --embedder ollama
# Adjust --cos-floor until 12/12 pass. Start at 0.35 and work up.
```

The selftest battery is the single-shot calibration — do it once before going live.

### 3. chunk_class filter (quality of life)

TOC pages, index pages, and boilerplate (revision history, copyright notices) are currently searchable but should never be the top citation for a technical query. Tag these chunks as `chunk_class: toc` or `chunk_class: boilerplate` during ingest and filter them from ranked results (but keep them searchable for part-number / page-reference lookups).

### 4. fastener label coverage ~60%

Torque VALUES extract correctly from all manuals. About 40% of specs lack a clean "what does this bolt attach to" label due to dense table layouts and hyphenation artifacts. This is cosmetic — the rendered page is always shown to the user for verification. Do not attempt to fix this with post-processing; it is a known acceptable limitation.

---

## Environment requirements (user's TrueNAS box)

```
Python 3.11+
pip install pymupdf pdfplumber sentence-transformers rank-bm25 numpy flask httpx
pip install openai-whisper yt-dlp   # Phase 2B video pipeline

ffmpeg on PATH:
  Windows: winget install ffmpeg
  Linux:   apt install ffmpeg

Ollama running at http://localhost:11434 with:
  - qwen3:14b          (generation)
  - nomic-embed-text   (embeddings, production)

poppler-utils         (for pdfunite if re-running large PDF splits)
```

For the dev/sandbox environment (where you're running now), use `--embedder local` (MiniLM) — it runs offline without Ollama.

---

## Hard rules — never drift from these

1. **No manual citation, no technical answer.** The core rule, always.
2. **Source PDFs are canonical.** Never modify them. Editing a source PDF breaks page-anchored citations for every existing chunk.
3. **Clean PDFs are reading copies only.** Never feed a `*_clean.pdf` to `ingest_manual.py`. Different `source_hash` = phantom citations.
4. **Safety warnings are content, not noise.** "Replace" (stretch bolt), "Safety note:", and "Warning:" text is never stripped during chunking.
5. **Torque specs are verbatim.** Angle stages ("+ 180°"), tolerances ("± 0.4 Nm"), and units must be reproduced exactly. No rounding, no conversion.
6. **specverify is not optional.** `verify_answer()` must gate every generated response. It cannot be skipped for speed or convenience.
7. **DTC cross-contamination is a safety bug.** The DTC chart QSB needs engine-code qualifiers per chunk before ingestion. Do not ingest it without this.
8. **Keep everything local and auth-gated.** Factory manual content is VW-copyrighted. Never expose it via a public endpoint or unauthenticated API.
9. **Never tune ranking without measuring.** `eval_ranking.py` is the baseline. Any retrieval changes must be measured against it. Hand-tuning that isn't measured is not an improvement.
10. **Videos are community tier — always.** `safety_tier = "community"` on every video chunk, forever. This tag must never be changed even if you trust the source. It controls whether specverify is called.
11. **Video conflicts surface, never resolve.** If a video says 30 Nm and the manual says 25 Nm, the answer must show both values and tell the user to follow the manual. Never pick one silently.

---

## Quick reference: key commands

```bash
# ── MANUALS ──────────────────────────────────────────────────────────
# Check what's already indexed
python -c "import json; idx=json.load(open('library_index.json')); print([m['manual_id'] for m in idx['manuals']])"

# Ingest a new manual (always originals, never clean PDFs)
python ingest_manual.py ingest <original.pdf> --manual-id <id> --title "<t>" --vehicle "2014 VW CC 2.0T TSI" --system "<s>" --out ./out

# Audit torque extraction (run after every new manual)
python specverify.py audit

# Check manual retrieval
python retrieve.py --selftest
python retrieve.py "camshaft bearing cap torque" -k 5

# Calibrate manual embedder floors on Ollama
python retrieve.py --selftest --embedder ollama

# Extract specs from a specific manual page
python specverify.py extract vw_cc_brakes_2011 47

# ── VIDEOS ───────────────────────────────────────────────────────────
# Inspect a video before ingesting
python ingest_video.py inspect "/path/to/video.mp4"

# Ingest a single video (local file)
python ingest_video.py ingest "/path/to/video.mp4" \
  --video-id my_video_01 --title "..." --channel "..." \
  --vehicle "2014 VW CC 2.0T TSI DSG" --system "DSG/DQ250" --out ./out

# Batch ingest
python ingest_video.py ingest-batch videos.txt --out ./out

# List all videos
python ingest_video.py list-videos --out ./out

# Review spec conflicts found in video transcripts
python ingest_video.py conflicts --out ./out

# Test video retrieval
python retrieve_video.py "DSG fluid change" -k 5 --out ./out
python retrieve_video.py --selftest --out ./out
```

---

## What Warwick needs to provide

1. **Original (watermarked) PDFs** for the ~24 unindexed manuals — upload them for ingestion. Do NOT upload the `*_clean.pdf` versions.
2. **DSG/DQ250 manual** — the 09M manual covers the wrong gearbox. Source the correct DQ250/02E manual.
3. **Ollama confirmation** — confirm `qwen3:14b` and `nomic-embed-text` are pulled on TrueNAS (`ollama list`).
4. **UI preference** — web app (Flask/FastAPI), CLI tool, or chat-style interface? This affects Phase 3 structure.
5. **Video file list** — for each video file provide: local path, a short video_id, title, channel name, and which car system it covers. Use `videos.txt` batch format (see Phase 2B above). Claude Code can generate the batch file once Warwick provides the list.

---

*End of handover. All source scripts are in `vw_rag_phase2b.zip`. The deep technical notes (rawdict gotcha, numpy intersection, chunk-splitting workaround, font substitution details) are in `HANDOFF.md` inside that zip.*
