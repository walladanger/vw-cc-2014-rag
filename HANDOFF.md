# VAG Manual RAG — Project Handoff

Paste this whole file (or its contents) into a new chat to continue. Upload the
three scripts + library_index.json alongside it, plus whatever new manuals you
have. Opening line to use: *"Continue the VAG manual-backed RAG project. Here are
the pipeline scripts and the library index — process these new manuals the same way."*

## What this project is
A local-first, manual-backed RAG "mechanic assistant" for a 2014 VW CC (2.0T TSI,
DSG). Core rule: **no manual citation, no technical answer.** The factory PDFs are
the canonical source; everything else (chunks, markdown, embeddings) is a support
layer. Safety-critical values (torque specs especially) are NEVER paraphrased —
they're extracted verbatim, page-cited, and verified character-for-character.

## The three scripts (the actual product)
1. **ingest_manual.py** — turns a raw PDF into page-anchored chunks + cleaned
   markdown + rendered diagram images.
     - `python ingest_manual.py inspect <pdf>`  → page count, diagram pages, OCR-needed pages, headings
     - `python ingest_manual.py ingest <pdf> --manual-id <id> --title "<t>" --vehicle "<v>" --system "<s>" --out ./out`
     - flags: `--no-render` (text layers only, fast re-index), `--render-all`, `--dpi`, `--max-chars`
     - Handles two VW watermark styles (curved diagonal + gray-apex) and trailing-verb
       VAG task titles ("Throttle Body, Replacing"). Records BOTH physical page (viewer
       target) and printed page label (often chapter-relative in VW manuals).
     - Requires: `pip install --break-system-packages pymupdf pdfplumber` + poppler.
0. **dewatermark_pdf.py** (v2, bonus utility — NOT part of the RAG pipeline) — strips
   the VAG copyright watermark from a PDF for human readability. Separate from the
   canonical source PDFs the pipeline indexes.
     - `python dewatermark_pdf.py <in.pdf>` → `<in>_clean.pdf`
     - `python dewatermark_pdf.py <dir>` → batch-process a folder
     - `python dewatermark_pdf.py <in.pdf> --dry-run` → count glyphs, write nothing
     - `python dewatermark_pdf.py <in.pdf> --inspect 5` → before/after PNGs for page 5
     - `python dewatermark_pdf.py <in.pdf> --no-restore` → skip body-text restoration
     - Requires: `pip install --break-system-packages pymupdf numpy`
     - numpy optional (pure-Python fallback available, but much slower on dense pages)
2. **retrieve.py** — hybrid retrieval (BM25 + dense) + the grounding gate.
     - `python retrieve.py --selftest` (12-case in/out-of-scope battery, should pass 12/12)
     - `python retrieve.py "spark plug gap" -k 3`
     - Embedder is pluggable: `--embedder local` (MiniLM, offline demo) or
       `--embedder ollama` (nomic-embed-text on TrueNAS, the production path).
     - Gate: ACCEPT only if dense cosine ≥ floor OR verified-lexical (query terms
       literally present). Floors calibrated for MiniLM — RE-CALIBRATE for nomic
       (run --selftest --embedder ollama once, adjust --cos-floor).
3. **specverify.py** — the safety layer. Extracts torque specs verbatim INCLUDING
   angle stages ("40 Nm + 180°"), tolerances ("2.2 Nm ± 0.4 Nm"), and stretch-bolt
   "Replace" flags. `verify_answer()` rejects any number not matching a cited chunk.
     - `python specverify.py selftest` (5/5, includes the dropped-angle-stage catch)
     - `python specverify.py audit` | `python specverify.py extract <manual_id> <page>`
(eval_ranking.py is an optional ranking-quality harness; baseline scores 1.00/1.00.)

## Library already processed (8 manuals, 1921 pages, 6361 chunks)
Dedup by source_hash is in library_index.json — the new chat should hash-check each
upload and SKIP if it matches. Already done:
  - vw_passat_cc_maint_2023  (Maintenance)
  - vw_cc_electrical_2018    (Electrical / wiring, exploded views)
  - vw_ea888_18_20_repair    (Engine Mechanical, 1.8/2.0 TSI)
  - vw_cc_2014_qsb           (Quick Reference Spec Book — engine/trans)
  - vw_cc_brakes_2011        (Brakes — safety-critical, 9 stretch bolts flagged)
  - vw_cc_2014_body_qsb      (Body QSB)
  - vw_ac_r1234yf_servicing  (A/C refrigerant R1234yf)
  - vw_09m_auto_trans_2019   (6-speed auto 09M)

## Known items / decisions still open
- **DTC chart QSB**: NOT processed yet (user holding it). When done, it needs an
  ENGINE-CODE qualifier per chunk — same fault code (e.g. misfire rate) has DIFFERENT
  threshold values for CBFA vs CCTA vs CNNA. Cross-contamination here is a safety bug.
- **09M transmission**: that's the Aisin auto. User's CC is DSG — confirm whether the
  09M manual even applies, or get the DSG/DQ250 manual instead.
- **Fastener-label coverage ~60%**: torque VALUES extract correctly; ~40% lack a clean
  "what it bolts to" label (dense table layouts). A few have hyphenation artifacts.
  Cosmetic, not a value error — but means the rendered page is the required human check.
- **New-manual rule**: always re-audit torque extraction (`specverify.py audit`) on a
  new manual before trusting its numbers — regex is tuned to these 8 manuals.

## Not yet built (next milestones, in rough priority)
1. Generation: wire Ollama (Qwen 3 14B suggested) to the citation context, constrained
   so every number copies a verified spec via specverify, gated through verify_answer().
   NEEDS the user's box — can't be proven in sandbox.
2. PDF viewer route `/viewer?manual={id}&page={n}` — the human verification step.
3. chunk_class filter (tag TOC/boilerplate as non-answerable, keep searchable).
4. Callout-overlay how-to diagrams (exploded views already carry numbered legends).

## Session 2 — De-watermarking pass (June 2026)

### What was done
Three factory service PDFs were de-watermarked using `dewatermark_pdf.py`:

| File | Pages | WM glyphs | Body chars restored |
|------|-------|-----------|---------------------|
| D3E803B616F-Maintenance_Procedures | 6 | — | 6 |
| D3E804F2326-Generic_Scan_Tool | 773 | — | 46,068 |
| D3E8001F4DC-Heating_Ventilation_and_Air_Conditioning | 167 | — | 10,847 |

Output files are `*_clean.pdf`. They are **reading copies only** — NOT re-ingested
into the RAG pipeline. The source PDFs remain canonical.

### Key discovery: body-text collateral damage

PyMuPDF's `apply_redactions()` removes ALL content within each redaction bbox, not
just the targeted glyph. On pages where VAG watermark glyphs overlap body-text
characters (common on dense technical pages), this erased legitimate text — notably
on the Generic Scan Tool manual (46 K chars on 773 pages).

**The fix (now baked into dewatermark_pdf.py v2):** before redacting each page,
scan with `get_text("rawdict")` to collect every body-text character whose bbox
intersects a watermark glyph rect. After `apply_redactions()`, re-insert those
characters at their exact original positions using `fitz.TextWriter`, substituting
the closest base-14 font (helv/tiro/cour variants) based on span flags.

### rawdict gotcha (critical for future work)
In `get_text("rawdict")` mode, `span["text"]` is always `""`. Text must be built
from `span["chars"]`: `"".join(c.get("c","") for c in span.get("chars",[]))`.
This is handled transparently by `_span_text()` in v2.

### numpy vectorised intersection
Checking which body chars intersect watermark rects with Python loops is too slow on
dense pages (e.g. 1942 chars × 287 wm rects = 557K fitz.Rect calls → timeout).
v2 uses a numpy broadcast `(n_chars, n_wm)` no-intersection array — ~250× faster.
Falls back to pure-Python if numpy is not installed.

### Sandbox-specific chunking (not needed on your machine)
The dev sandbox has a 45-second per-call hard timeout. The 773-page Generic Scan Tool
PDF required splitting into 100-page chunks, processing each independently, then
merging with `pdfunite`. On your local machine there is no such constraint — the v2
script processes large PDFs in a single pass without chunking.

### Fonts substituted
The original embedded proprietary VAG/Myriad fonts cannot be transferred to a new
TextWriter. v2 substitutes base-14 PDF fonts based on span flags:
- `helv`/`hebo`/`heit` — Helvetica variants (sans-serif, the dominant VAG body font)
- `tiro`/`tibo`/`tiit`/`tibi` — Times Roman variants (serif)
- `cour`/`cobo`/`coit` — Courier variants (monospaced)
Visual result on restored chars is nearly identical for sans-serif body text.

---

## Hard principles (do not drift from these)
- PDFs are canonical; never edit the source PDFs (breaks page-anchored citations).
- Safety warnings and "Replace" flags are content, not noise — never strip them.
- The model is swappable; the index is the product. No fine-tuning of facts.
- Derivative outputs are VW-copyrighted — keep local/auth-gated, never public.
