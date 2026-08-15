#!/usr/bin/env python3
"""
Community Guide Ingestion Pipeline (v1) — third-party PDF repair guides.

Ingests step-by-step repair guide PDFs (e.g. AUTO DOC CLUB) as community-tier
chunks alongside — but strictly separate from — the canonical factory manuals.

SAFETY CONTRACT  (same as ingest_video.py — never relax these)
  - ALL chunks produced here are tagged  safety_tier = "community"
  - They must NEVER be passed to specverify.verify_answer()
  - Torque values found in guide text trigger a conflict log entry — NOT an answer
  - The generator must present these as "see also", never as primary spec source
  - If a guide value conflicts with a factory manual value, SURFACE the conflict —
    never silently resolve it in the guide's favour
  - Chunks flagged  diesel_only = True  must not be surfaced for TSI/petrol queries

Output layout:
  out/guides/<guide_id>/
    manifest.json     guide-level metadata
    chunks.jsonl      one step-anchored chunk per line (with embedding)
  out/guide_index.json  dedup registry (hash-based, like library_index.json)

Usage:
  python ingest_guide.py inspect <pdf>
  python ingest_guide.py ingest  <pdf> \\
      --guide-id vw_cc_front_brakes_autodoc \\
      --title "How to change front brake pads on VW CC (358)" \\
      --channel "AUTO DOC CLUB" \\
      --vehicle "2014 VW CC 2.0T TSI" \\
      --system "Brakes/Front" \\
      --out ./out

  python ingest_guide.py ingest-batch guides.jsonl --out ./out
  python ingest_guide.py list-guides  --out ./out
  python ingest_guide.py conflicts    --out ./out

Dependencies:
  pip install pymupdf rank-bm25 numpy
Optional:
  pip install sentence-transformers    # local embedder
  pip install httpx                    # Ollama embedder
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from applicability import BLANK_REASON, VEHICLE_HELP, validate_vehicle, vehicle_arg

# ──────────────────────────────────────────── optional deps

def _import_fitz():
    try:
        import fitz
        return fitz
    except ImportError:
        sys.exit("PyMuPDF not installed.  Run:  pip install pymupdf")

def _embed_local(texts):
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(texts, show_progress_bar=False).tolist()
    except ImportError:
        print("  Warning: sentence-transformers not installed — skipping embeddings.",
              file=sys.stderr)
        return [[] for _ in texts]

def _embed_ollama(texts, base="http://localhost:11434"):
    import httpx
    out = []
    for t in texts:
        r = httpx.post(f"{base}/api/embeddings",
                       json={"model": "nomic-embed-text", "prompt": t}, timeout=30)
        out.append(r.json()["embedding"])
    return out

# ──────────────────────────────────────────── constants

PIPELINE_VERSION = "ingest-guide-v1"
GUIDE_INDEX_NAME = "guide_index.json"

# Numbered step patterns (AUTO DOC CLUB style: "1.", "Step 1", "1)")
STEP_RE = re.compile(r"^\s*(?:step\s+)?(\d{1,2})[.)]\s+", re.IGNORECASE)

# Warning / caution / note markers — must never be stripped
SAFETY_LINE_RE = re.compile(
    r"^\s*(warning|caution|note|important|attention|replace|do not|never)\b",
    re.IGNORECASE,
)

# Torque / spec patterns — same regex as ingest_video.py
TORQUE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:nm|newton.?met(?:er|re)|foot.?pound|ft.?lb|"
    r"in.?lb|n\.m)\b"
    r"|(?:torque|tighten(?:ing)?|torqued?)\s+(?:to|at|is|of)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
SPEC_KEYWORDS_RE = re.compile(
    r"\b(stretch bolt|replace after|one.?time use|cannot be reused|"
    r"single.?use|fluid capacit|change interval|gap spec|clearance)\b",
    re.IGNORECASE,
)

CHUNK_TARGET_WORDS = 150
CHUNK_MAX_WORDS    = 300

# ──────────────────────────────────────────── helpers

def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()

def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(buf), b""):
            h.update(block)
    return h.hexdigest()

def word_count(text):
    return len(text.split())

def safe_id(s):
    return re.sub(r"[^\w]", "_", s)[:48].lower().strip("_")

# ──────────────────────────────────────────── PDF text extraction

def extract_pages(pdf_path):
    """
    Returns list of (page_idx, page_text) tuples.
    Strips non-horizontal text (watermarks) the same way ingest_manual.py does,
    though AUTO DOC CLUB guides usually don't have VAG-style watermarks.
    """
    fitz = _import_fitz()
    doc  = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        data  = page.get_text("dict")
        lines = []
        for block in data.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                d = line.get("dir", (1, 0))
                # Skip non-horizontal text (watermarks, vertical labels)
                if not (d[0] >= 0.95 and abs(d[1]) <= 0.15):
                    continue
                text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if text:
                    lines.append(text)
        pages.append((i, "\n".join(lines)))
    doc.close()
    return pages

# ──────────────────────────────────────────── chunking

def chunk_pages(pages):
    """
    Chunk guide text into procedure-step chunks.
    Strategy:
      1. Collect all text into lines
      2. Split at numbered step boundaries or section headings
      3. Merge short lines up to CHUNK_TARGET_WORDS
    Returns list of {"step_label", "page_start", "page_end", "text"}
    """
    # Flatten all lines with page tracking
    all_lines = []  # (page_idx, line_text)
    for page_idx, text in pages:
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                all_lines.append((page_idx, ln))

    if not all_lines:
        return []

    # Find step / section boundaries
    boundaries = set()
    for i, (_, ln) in enumerate(all_lines):
        if STEP_RE.match(ln):
            boundaries.add(i)
        # Bold-looking ALL CAPS short line = section heading
        elif ln.isupper() and 2 < len(ln.split()) <= 10:
            boundaries.add(i)

    # Always start a chunk at line 0
    boundaries.add(0)
    boundary_list = sorted(boundaries)

    raw_chunks = []
    for b_idx, start in enumerate(boundary_list):
        end = boundary_list[b_idx + 1] if b_idx + 1 < len(boundary_list) else len(all_lines)
        chunk_lines = all_lines[start:end]
        if not chunk_lines:
            continue
        text = "\n".join(ln for _, ln in chunk_lines).strip()
        page_start = chunk_lines[0][0]
        page_end   = chunk_lines[-1][0]
        step_m     = STEP_RE.match(chunk_lines[0][1])
        step_label = f"Step {step_m.group(1)}" if step_m else ""
        raw_chunks.append({
            "step_label":  step_label,
            "page_start":  page_start + 1,   # 1-indexed for display
            "page_end":    page_end   + 1,
            "text":        text,
        })

    # Merge very small chunks into the previous one
    merged = []
    for rc in raw_chunks:
        if (merged
                and not rc["step_label"]          # not a numbered step
                and word_count(merged[-1]["text"]) + word_count(rc["text"]) <= CHUNK_MAX_WORDS):
            merged[-1]["text"]     += "\n" + rc["text"]
            merged[-1]["page_end"]  = rc["page_end"]
        else:
            merged.append(rc)

    return merged

# ──────────────────────────────────────────── conflict detection

def detect_conflicts(text):
    conflicts = []
    for m in TORQUE_RE.finditer(text):
        value = m.group(1) or m.group(2)
        conflicts.append({
            "type":    "torque_value",
            "value":   value,
            "context": text[max(0, m.start()-50):m.end()+50].replace("\n", " "),
        })
    for m in SPEC_KEYWORDS_RE.finditer(text):
        conflicts.append({
            "type":    "spec_keyword",
            "keyword": m.group(0),
            "context": text[max(0, m.start()-50):m.end()+50].replace("\n", " "),
        })
    return conflicts

# ──────────────────────────────────────────── embed

def embed_texts(texts, embedder="local", ollama_base="http://localhost:11434"):
    if embedder == "ollama":
        try:
            return _embed_ollama(texts, base=ollama_base)
        except Exception as e:
            print(f"  Ollama embed failed ({e}), falling back to local", file=sys.stderr)
    return _embed_local(texts)

# ──────────────────────────────────────────── index helpers

def load_guide_index(out_dir):
    path = os.path.join(out_dir, GUIDE_INDEX_NAME)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"pipeline_version": PIPELINE_VERSION, "guides": []}

def save_guide_index(index, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, GUIDE_INDEX_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

def index_has_guide(index, guide_id):
    return any(g["guide_id"] == guide_id for g in index.get("guides", []))

def index_has_hash(index, source_hash):
    return any(g.get("source_hash") == source_hash for g in index.get("guides", []))

# ──────────────────────────────────────────── main ingest

def ingest_guide(
    pdf_path,
    guide_id,
    title,
    channel,
    vehicle,
    system,
    out_dir,
    diesel_only=False,
    embedder="local",
    ollama_base="http://localhost:11434",
    skip_embed=False,
    force=False,
    notes="",
):
    # Last line of defence. The CLI and the batch loader both check this earlier
    # and with better messages, but run_ingest_guides.py imports this function
    # directly, so the guard belongs at the point where chunks are stamped.
    try:
        vehicle = validate_vehicle(vehicle)
    except ValueError as exc:
        print(f'  ⚠  {guide_id}: "vehicle" {exc}', file=sys.stderr)
        return False

    if not os.path.isfile(pdf_path):
        print(f"  ⚠  File not found: {pdf_path}", file=sys.stderr)
        return False

    source_hash = sha256_file(pdf_path)
    index = load_guide_index(out_dir)

    if not force:
        if index_has_guide(index, guide_id):
            print(f"  ✓ {guide_id} already indexed — skipping (use --force to re-ingest)")
            return True
        if index_has_hash(index, source_hash):
            print(f"  ✓ {pdf_path} already indexed (same hash) — skipping")
            return True

    guide_out = os.path.join(out_dir, "guides", guide_id)
    os.makedirs(guide_out, exist_ok=True)

    # ── 1. Extract text
    print(f"[{guide_id}] Extracting text from {Path(pdf_path).name} …")
    pages = extract_pages(pdf_path)
    total_chars = sum(len(t) for _, t in pages)
    print(f"[{guide_id}] {len(pages)} pages, {total_chars:,} chars")

    # ── 2. Chunk
    raw_chunks = chunk_pages(pages)
    print(f"[{guide_id}] → {len(raw_chunks)} chunks")

    # ── 3. Build chunk objects
    all_conflicts = []
    chunk_objects = []
    for i, rc in enumerate(raw_chunks):
        chunk_id  = f"{guide_id}_c{i:04d}"
        conflicts = detect_conflicts(rc["text"])
        all_conflicts.extend([{"chunk_id": chunk_id, **c} for c in conflicts])
        chunk_objects.append({
            "chunk_id":          chunk_id,
            "guide_id":          guide_id,
            "safety_tier":       "community",   # NEVER pass to specverify
            "source_type":       "guide",
            "title":             title,
            "channel":           channel,
            "vehicle":           vehicle,
            "system":            system,
            "diesel_only":       diesel_only,   # if True, exclude for TSI queries
            "step_label":        rc["step_label"],
            "page_start":        rc["page_start"],
            "page_end":          rc["page_end"],
            "text":              rc["text"],
            "word_count":        word_count(rc["text"]),
            "has_spec_conflict": bool(conflicts),
            "spec_conflicts":    conflicts,
            "embedding":         [],
        })

    # ── 4. Embed
    if not skip_embed and chunk_objects:
        print(f"[{guide_id}] Embedding {len(chunk_objects)} chunks ({embedder}) …")
        texts = [c["text"] for c in chunk_objects]
        vecs  = embed_texts(texts, embedder=embedder, ollama_base=ollama_base)
        for c, v in zip(chunk_objects, vecs):
            c["embedding"] = v

    # ── 5. Write chunks.jsonl
    chunks_path = os.path.join(guide_out, "chunks.jsonl")
    with open(chunks_path, "w", encoding="utf-8") as f:
        for c in chunk_objects:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # ── 6. Write manifest
    manifest = {
        "guide_id":      guide_id,
        "title":         title,
        "channel":       channel,
        "vehicle":       vehicle,
        "system":        system,
        "diesel_only":   diesel_only,
        "source_path":   pdf_path,
        "source_hash":   source_hash,
        "page_count":    len(pages),
        "chunk_count":   len(chunk_objects),
        "conflict_count": len(all_conflicts),
        "safety_tier":   "community",
        "notes":         notes,
        "ingested_at":   now_iso(),
        "pipeline":      PIPELINE_VERSION,
    }
    with open(os.path.join(guide_out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # ── 7. Write conflict log if needed
    if all_conflicts:
        cf_path = os.path.join(guide_out, "spec_conflicts.json")
        with open(cf_path, "w", encoding="utf-8") as f:
            json.dump(all_conflicts, f, indent=2, ensure_ascii=False)
        print(f"[{guide_id}] ⚠  {len(all_conflicts)} spec conflicts logged → {cf_path}")

    # ── 8. Update guide_index.json
    entry = {**manifest, "chunks_path": chunks_path}
    index["guides"] = [g for g in index["guides"] if g["guide_id"] != guide_id]
    index["guides"].append(entry)
    save_guide_index(index, out_dir)

    diesel_note = "  ⚠  diesel_only=True — will be excluded for TSI queries" if diesel_only else ""
    print(f"[{guide_id}] ✓ Done — {len(chunk_objects)} chunks, {len(all_conflicts)} conflicts{diesel_note}")
    return True

# ──────────────────────────────────────────── batch ingest

def ingest_batch(batch_file, out_dir, embedder, ollama_base, skip_embed, force):
    """
    JSON-lines batch file. Each line:
    {"pdf_path": "...", "guide_id": "...", "title": "...", "channel": "...",
     "vehicle": "...", "system": "...", "diesel_only": false, "notes": ""}
    """
    with open(batch_file, "r", encoding="utf-8") as f:
        numbered = [(n, l.strip()) for n, l in enumerate(f, 1)
                    if l.strip() and not l.strip().startswith("#")]

    # Check applicability before any expensive work. An entry with no "vehicle"
    # stamps chunks that match every car (see applicability.py), so the batch is
    # refused as a whole rather than ingesting the good entries and leaving the
    # unstamped ones to surface later as another car's spec reported VERIFIED.
    entries, unstamped = [], []
    for line_no, line in numbered:
        entry = json.loads(line)
        try:
            entry["vehicle"] = validate_vehicle(entry.get("vehicle"))
        except ValueError:
            unstamped.append((line_no, entry.get("guide_id") or "?"))
        entries.append(entry)

    if unstamped:
        print(f"Refusing batch: {len(unstamped)} of {len(entries)} entries have no "
              f'"vehicle".', file=sys.stderr)
        for line_no, guide_id in unstamped:
            print(f"  line {line_no}: {guide_id}", file=sys.stderr)
        print(f'\n"vehicle" {BLANK_REASON}', file=sys.stderr)
        raise SystemExit(2)

    print(f"Batch: {len(entries)} guides")
    ok = err = 0
    for entry in entries:
        success = ingest_guide(
            pdf_path    = entry["pdf_path"],
            guide_id    = entry["guide_id"],
            title       = entry.get("title", ""),
            channel     = entry.get("channel", ""),
            vehicle     = entry["vehicle"],
            system      = entry.get("system", ""),
            diesel_only = entry.get("diesel_only", False),
            notes       = entry.get("notes", ""),
            out_dir     = out_dir,
            embedder    = embedder,
            ollama_base = ollama_base,
            skip_embed  = skip_embed,
            force       = force,
        )
        if success:
            ok += 1
        else:
            err += 1
    print(f"\nBatch complete: {ok} succeeded, {err} failed")

# ──────────────────────────────────────────── inspect / list / conflicts

def inspect_guide(pdf_path):
    if not os.path.isfile(pdf_path):
        print(f"File not found: {pdf_path}")
        return
    pages = extract_pages(pdf_path)
    chunks = chunk_pages(pages)
    print(f"\nFile:   {Path(pdf_path).name}")
    print(f"Pages:  {len(pages)}")
    print(f"Chunks: {len(chunks)}")
    conflicts = sum(len(detect_conflicts(c["text"])) for c in chunks)
    print(f"Spec conflicts detected: {conflicts}")
    print("\nFirst 5 chunks:")
    for c in chunks[:5]:
        label = f"[{c['step_label']}] " if c["step_label"] else f"[p.{c['page_start']}] "
        print(f"  {label}{c['text'][:120].replace(chr(10), ' ')}…")

def list_guides(out_dir):
    index = load_guide_index(out_dir)
    guides = index.get("guides", [])
    if not guides:
        print("No guides indexed yet.")
        return
    print(f"{'guide_id':<40} {'chunks':>6} {'conf':>4}  {'D':>1}  title")
    print("-" * 90)
    for g in guides:
        d = "D" if g.get("diesel_only") else " "
        print(f"{g['guide_id']:<40} {g['chunk_count']:>6} {g['conflict_count']:>4}  {d}  {g['title'][:40]}")
    print(f"\nD = diesel_only (not applicable to TSI/petrol variants)")

def show_conflicts(out_dir):
    index = load_guide_index(out_dir)
    any_found = False
    for g in index.get("guides", []):
        cf_path = os.path.join(out_dir, "guides", g["guide_id"], "spec_conflicts.json")
        if not os.path.isfile(cf_path):
            continue
        with open(cf_path, "r", encoding="utf-8") as f:
            conflicts = json.load(f)
        if not conflicts:
            continue
        any_found = True
        print(f"\n{'='*60}")
        print(f"GUIDE: {g['guide_id']}")
        print(f"  {g['title']}")
        print(f"{'='*60}")
        for c in conflicts:
            print(f"  [{c['type']}] chunk={c['chunk_id']}")
            if c.get("value"):
                print(f"    value:   {c['value']} Nm")
            if c.get("keyword"):
                print(f"    keyword: {c['keyword']}")
            print(f"    context: …{c['context']}…")
    if not any_found:
        print("No spec conflicts found.")
    else:
        print("\n⚠  Cross-check every value above against the factory manual.")

# ──────────────────────────────────────────── CLI

def main():
    parser = argparse.ArgumentParser(
        description="Ingest community repair guide PDFs (AUTO DOC CLUB etc.) — community tier.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="Preview a PDF without ingesting")
    p_ins.add_argument("pdf")

    p_ing = sub.add_parser("ingest", help="Ingest a single guide PDF")
    p_ing.add_argument("pdf")
    p_ing.add_argument("--guide-id",    required=True)
    p_ing.add_argument("--title",       default="")
    p_ing.add_argument("--channel",     default="AUTO DOC CLUB")
    p_ing.add_argument("--vehicle",     required=True, type=vehicle_arg,
                                        help=VEHICLE_HELP)
    p_ing.add_argument("--system",      default="")
    p_ing.add_argument("--diesel-only", action="store_true")
    p_ing.add_argument("--notes",       default="")
    p_ing.add_argument("--out",         default="./out")
    p_ing.add_argument("--embedder",    default="local", choices=["local", "ollama"])
    p_ing.add_argument("--ollama-base", default="http://localhost:11434")
    p_ing.add_argument("--skip-embed",  action="store_true")
    p_ing.add_argument("--force",       action="store_true")

    p_bat = sub.add_parser("ingest-batch", help="Ingest from a JSON-lines batch file")
    p_bat.add_argument("batch_file")
    p_bat.add_argument("--out",         default="./out")
    p_bat.add_argument("--embedder",    default="local", choices=["local", "ollama"])
    p_bat.add_argument("--ollama-base", default="http://localhost:11434")
    p_bat.add_argument("--skip-embed",  action="store_true")
    p_bat.add_argument("--force",       action="store_true")

    p_lst = sub.add_parser("list-guides", help="List all indexed guides")
    p_lst.add_argument("--out", default="./out")

    p_con = sub.add_parser("conflicts", help="Show spec conflict log")
    p_con.add_argument("--out", default="./out")

    args = parser.parse_args()

    if args.cmd == "inspect":
        inspect_guide(args.pdf)
    elif args.cmd == "ingest":
        ingest_guide(
            pdf_path    = args.pdf,
            guide_id    = args.guide_id,
            title       = args.title,
            channel     = args.channel,
            vehicle     = args.vehicle,
            system      = args.system,
            diesel_only = args.diesel_only,
            notes       = args.notes,
            out_dir     = args.out,
            embedder    = args.embedder,
            ollama_base = args.ollama_base,
            skip_embed  = args.skip_embed,
            force       = args.force,
        )
    elif args.cmd == "ingest-batch":
        ingest_batch(
            batch_file  = args.batch_file,
            out_dir     = args.out,
            embedder    = args.embedder,
            ollama_base = args.ollama_base,
            skip_embed  = args.skip_embed,
            force       = args.force,
        )
    elif args.cmd == "list-guides":
        list_guides(args.out)
    elif args.cmd == "conflicts":
        show_conflicts(args.out)


if __name__ == "__main__":
    main()
