#!/usr/bin/env python3
"""
VAG Manual Ingestion Pipeline (v1) -- citation-first, diagram-aware.

Takes a raw, unprocessed VW / Audi / VAG PDF manual and produces the local
"support layers" from the project spec WITHOUT needing any backend running:

  out/<manual_id>/
    manifest.json            manual-level metadata + diagram / ocr page index
    chunks.jsonl             one page-anchored chunk per line (ready to embed)
    manual.md                cleaned, page-anchored markdown (hand-editable)
    diagrams/
      page_0123.png          full-page render of each diagram page (vision-ready)
      page_0123_img01.png     embedded raster image(s) pulled off that page

Design rules baked in:
  * CITATION FIRST. Every chunk is anchored to exactly ONE physical PDF page,
    so a citation always resolves to a single openable page. Both the physical
    page index (what the viewer jumps to) and the printed page label (what the
    manual prints on the page) are recorded -- they rarely match in factory PDFs.
  * DIAGRAM AWARE. Text extraction is blind to wiring diagrams, exploded views,
    fuse tables drawn as graphics, etc. Those pages are detected, rendered to
    PNG so a vision model can READ them, and flagged on every chunk.
  * PDFs STAY CANONICAL. We only emit support layers; nothing here mutates the
    source PDF. source_hash ties every chunk back to the exact file it came from.

Usage:
  python ingest_manual.py inspect <pdf>
  python ingest_manual.py ingest  <pdf> \
      --manual-id vw_cc_2014_repair \
      --title "VW CC 2014 Repair Manual" \
      --vehicle "2014 Volkswagen CC" --engine "2.0T TSI" --year 2014 \
      --out ./out
"""
import argparse
import collections
import datetime as _dt
import hashlib
import json
import os
import re
import sys

import fitz  # PyMuPDF

PIPELINE_VERSION = "ingest-v1"

# Lines that look like the start of a service procedure / spec block. Used as a
# fallback heading signal on top of font-size analysis, tuned for VAG manuals.
PROC_REGEX = re.compile(
    r"^\s*(removing and installing|removing|installing|checking|replacing|"
    r"renewing|adjusting|testing|disconnecting|connecting|assembly overview|"
    r"exploded view|wiring diagram|fuse|relay|torque|tightening (torque|spec)|"
    r"technical data|specifications?|fluid|capacities|diagnos|fault finding|"
    r"general notes|safety|special tools?)\b",
    re.IGNORECASE,
)
PAGENUM_ONLY = re.compile(r"^\s*[-–]?\s*\d{1,4}\s*[-–]?\s*$")

# VAG manuals name tasks "Component ..., Action" with the verb LAST
# (e.g. "Dust and Pollen Filter, Replacing"). The procedure regex above is
# anchored to the start of the line, so this catches the trailing-verb style.
TASK_TAIL_REGEX = re.compile(
    r",\s*(removing|installing|replacing|renewing|changing|checking|adding|"
    r"cleaning|adjusting|inspecting|lubricating|topping up|draining|filling|"
    r"testing|reading|servicing|resetting|measuring|bleeding)\b",
    re.IGNORECASE,
)

# ----------------------------------------------------------------------------- helpers


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(buf), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _horizontal(dirv):
    """True for normal left-to-right text. Rotated lines (dir off the x-axis)
    are the diagonal VW copyright watermark or vertical labels."""
    return dirv[0] >= 0.99 and abs(dirv[1]) <= 0.05


def page_lines(page, drop_watermark=True):
    """Reading-order lines with size/bold info from the text dict.

    The VW factory watermark ("Protected by copyright ...") is rendered as a
    curve of individually-rotated glyphs that otherwise shred text extraction.
    We drop non-horizontal lines and tiny low-size fragments to remove it."""
    out = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:  # 0 == text block
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            if drop_watermark and not _horizontal(line.get("dir", (1, 0))):
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            max_size = max(s.get("size", 0) for s in spans)
            # The watermark is small light-gray text; body text is pure black
            # (color 0). A few watermark glyphs at the curve apex are nearly
            # horizontal and pass the angle test, so also drop short gray
            # fragments below body size.
            entirely_gray = all(s.get("color", 0) != 0 for s in spans)
            if drop_watermark and max_size <= 8.6 and entirely_gray and len(text) <= 12:
                continue
            bold = any(
                (s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower()
                for s in spans
            )
            out.append({"text": text, "size": round(max_size, 1), "bold": bold})
    return out


def detect_body_size(doc, sample=25):
    """Most common rounded font size across a page sample == body text size."""
    counter = collections.Counter()
    step = max(1, len(doc) // sample)
    for i in range(0, len(doc), step):
        for ln in page_lines(doc[i]):
            counter[ln["size"]] += len(ln["text"])
    return counter.most_common(1)[0][0] if counter else 10.0


def is_heading(ln, body_size):
    t = ln["text"]
    words = t.split()
    if PAGENUM_ONLY.match(t):
        return False
    if PROC_REGEX.match(t) and len(words) <= 16:
        return True
    if TASK_TAIL_REGEX.search(t) and len(words) <= 16:
        return True
    if len(words) > 14:
        return False
    if ln["size"] >= body_size * 1.12:
        return True
    if ln["bold"] and len(words) <= 10 and len(t) >= 3:
        return True
    return False


def printed_label(page, idx):
    """Best-effort printed page label: PDF page-label first, then a bare number
    near the bottom of the page."""
    try:
        lbl = page.get_label()
        if lbl:
            return lbl
    except Exception:
        pass
    lines = page.get_text("text").strip().splitlines()
    for ln in lines[-3:][::-1]:
        m = re.match(r"^\s*[-–]?\s*(\d{1,4})\s*[-–]?\s*$", ln.strip())
        if m:
            return m.group(1)
    return None


def diagram_profile(page):
    """Return (has_diagram, needs_ocr, image_coverage, vector_count, text_chars)."""
    rect = page.rect
    page_area = max(1.0, rect.width * rect.height)
    # Real text only -- exclude the rotated copyright watermark, which would
    # otherwise make image-only pages look text-rich.
    text_chars = sum(len(ln["text"]) for ln in page_lines(page))

    img_area = 0.0
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for r in page.get_image_rects(xref):
                img_area += r.width * r.height
        except Exception:
            pass
    coverage = min(1.0, img_area / page_area)

    try:
        vector_count = len(page.get_drawings())
    except Exception:
        vector_count = 0

    needs_ocr = text_chars < 40 and coverage > 0.5
    has_diagram = (
        coverage > 0.15
        or vector_count > 40
        or (text_chars < 220 and (coverage > 0.05 or vector_count > 10))
    )
    return has_diagram, needs_ocr, round(coverage, 3), vector_count, text_chars


def save_page_render(page, path, dpi):
    pix = page.get_pixmap(dpi=dpi)
    pix.save(path)


def save_embedded_images(doc, page, page_no, out_dir, min_px=64):
    saved = []
    for n, img in enumerate(page.get_images(full=True), start=1):
        xref = img[0]
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.width < min_px or pix.height < min_px:
                continue  # skip masks / decorative slivers
            if pix.n - pix.alpha > 3:  # CMYK -> RGB
                pix = fitz.Pixmap(fitz.csRGB, pix)
            fn = f"page_{page_no:04d}_img{n:02d}.png"
            pix.save(os.path.join(out_dir, fn))
            saved.append(fn)
        except Exception:
            continue
    return saved


def chunk_segment_text(text, max_chars):
    """Split overlong segment text on paragraph then sentence boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    paras = re.split(r"\n\s*\n", text)
    chunks, cur = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(cur) + len(p) + 2 <= max_chars:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            if len(p) <= max_chars:
                cur = p
            else:  # single giant paragraph -> sentence split
                cur = ""
                for sent in re.split(r"(?<=[.!?])\s+", p):
                    if len(cur) + len(sent) + 1 <= max_chars:
                        cur = f"{cur} {sent}".strip()
                    else:
                        if cur:
                            chunks.append(cur)
                        cur = sent
    if cur:
        chunks.append(cur)
    return chunks


def segment_page(lines, body_size, carried_section):
    """Break one page's lines into (section_title, body_text) segments,
    splitting whenever a heading is encountered. Carries the active section
    across page boundaries so continuation pages keep their context."""
    segments = []
    cur_title = carried_section
    cur_body = []

    def flush():
        body = "\n".join(cur_body).strip()
        if body:
            segments.append((cur_title or "(front matter)", body))

    for ln in lines:
        if PAGENUM_ONLY.match(ln["text"]):
            continue
        if is_heading(ln, body_size):
            flush()
            cur_title = ln["text"]
            cur_body = []
        else:
            cur_body.append(ln["text"])
    flush()
    if not segments:  # page was pure diagram / blank text
        segments.append((cur_title or "(diagram page)", ""))
    return segments, cur_title


# ----------------------------------------------------------------------------- commands


def cmd_inspect(args):
    doc = fitz.open(args.pdf)
    body = detect_body_size(doc)
    diagram_pages, ocr_pages, headings = [], [], []
    for i in range(len(doc)):
        page = doc[i]
        has_d, ocr, cov, vec, tc = diagram_profile(page)
        if has_d:
            diagram_pages.append(i + 1)
        if ocr:
            ocr_pages.append(i + 1)
        for ln in page_lines(page)[:40]:
            if is_heading(ln, body) and len(headings) < 25:
                headings.append((i + 1, ln["text"]))
    print(f"file            : {args.pdf}")
    print(f"pages           : {len(doc)}")
    print(f"body font size  : {body}")
    print(f"diagram pages   : {len(diagram_pages)}  {diagram_pages[:20]}{' ...' if len(diagram_pages) > 20 else ''}")
    print(f"likely scanned  : {len(ocr_pages)} page(s) need OCR  {ocr_pages[:20]}")
    print(f"sample headings :")
    for pno, h in headings:
        print(f"   p{pno:>4}  {h[:70]}")
    doc.close()


def cmd_ingest(args):
    pdf_path = os.path.abspath(args.pdf)
    manual_id = args.manual_id or re.sub(r"[^a-z0-9]+", "_", os.path.splitext(os.path.basename(pdf_path))[0].lower()).strip("_")
    title = args.title or manual_id
    base = os.path.join(args.out, manual_id)
    diag_dir = os.path.join(base, "diagrams")
    os.makedirs(diag_dir, exist_ok=True)

    src_hash = sha256_file(pdf_path)
    doc = fitz.open(pdf_path)
    body = detect_body_size(doc)

    chunks = []
    diagram_pages, ocr_pages = [], []
    carried = None
    md_lines = [
        f"# {title}",
        f"<!-- manual_id: {manual_id} | source_hash: {src_hash} | pipeline: {PIPELINE_VERSION} -->",
        f"<!-- vehicle: {args.vehicle} | engine: {args.engine} | year: {args.year} -->",
        "",
    ]

    for i in range(len(doc)):
        page = doc[i]
        page_no = i + 1
        has_d, ocr, cov, vec, tc = diagram_profile(page)
        label = printed_label(page, i)
        page_image = None
        image_refs = []

        wants_image = has_d or ocr or page_no == 1 or args.render_all
        if wants_image:
            page_image = f"diagrams/page_{page_no:04d}.png"  # deterministic path
        if wants_image and not args.no_render:
            save_page_render(page, os.path.join(diag_dir, f"page_{page_no:04d}.png"), args.dpi)
        if (has_d or ocr) and not args.no_render:
            image_refs = [f"diagrams/{f}" for f in save_embedded_images(doc, page, page_no, diag_dir)]
        if has_d:
            diagram_pages.append(page_no)
        if ocr:
            ocr_pages.append(page_no)

        lines = page_lines(page)
        segments, carried = segment_page(lines, body, carried)

        md_lines.append(f"<!-- page {page_no} (printed label: {label}) -->")
        seg_idx = 0
        for sec_title, body_text in segments:
            md_lines.append(f"## {sec_title}")
            if body_text:
                md_lines.append(body_text)
            pieces = chunk_segment_text(body_text, args.max_chars)
            # A diagram / scanned page may carry little or no extractable text.
            # It must STILL produce a chunk so the diagram is retrievable; the
            # page render (page_image) is the real content a vision model reads.
            if not pieces:
                if has_d or ocr:
                    pieces = [f"{sec_title} [diagram page \u2014 image content on page {page_no}]"]
                else:
                    continue
            for piece in pieces:
                seg_idx += 1
                chunks.append({
                    "source_type": "manual",
                    "chunk_id": f"{manual_id}_p{page_no:04d}_{seg_idx:02d}",
                    "manual_id": manual_id,
                    "manual_title": title,
                    "pdf_filename": os.path.basename(pdf_path),
                    "page_physical": page_no,      # what the viewer jumps to
                    "page_label": label,           # what the manual prints
                    "page_start": page_no,
                    "page_end": page_no,
                    "section_title": sec_title,
                    "system": args.system,
                    "vehicle": args.vehicle,
                    "engine": args.engine,
                    "model_year": args.year,
                    "text": piece,
                    "char_count": len(piece),
                    "has_diagram": has_d,
                    "needs_ocr": ocr,
                    "page_image": page_image,
                    "image_refs": image_refs,
                    "viewer_url": f"/viewer?manual={manual_id}&page={page_no}",
                    "source_hash": src_hash,
                    "chunk_hash": sha256_text(piece),
                    "created_at": now_iso(),
                })
        if page_image and (has_d or ocr):
            md_lines.append(f"![diagram p{page_no}]({page_image})")
        md_lines.append("")

    n_pages = len(doc)
    doc.close()

    with open(os.path.join(base, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(base, "manual.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    manifest = {
        "manual_id": manual_id,
        "manual_title": title,
        "pdf_filename": os.path.basename(pdf_path),
        "source_path": pdf_path,
        "source_hash": src_hash,
        "pages": n_pages,
        "body_font_size": body,
        "chunk_count": len(chunks),
        "diagram_pages": diagram_pages,
        "needs_ocr_pages": ocr_pages,
        "applicability": {"vehicle": args.vehicle, "engine": args.engine, "model_year": args.year, "system": args.system},
        "diagrams_rendered": not args.no_render,
        "pipeline_version": PIPELINE_VERSION,
        "created_at": now_iso(),
    }
    with open(os.path.join(base, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"[ok] {manual_id}")
    print(f"     pages={n_pages}  chunks={len(chunks)}  diagram_pages={len(diagram_pages)}  ocr_pages={len(ocr_pages)}")
    print(f"     -> {base}/  (manifest.json, chunks.jsonl, manual.md, diagrams/)")


def _vehicle_arg(value):
    """Reject a blank --vehicle as well as a missing one.

    retrieve.applies_to_vehicle admits any chunk with nothing stamped, so that
    scoping cannot silently empty an index built before applicability was
    enforced. The cost of failing open is that an unstamped manual matches EVERY
    car, which is the cross-vehicle bleed the filter exists to prevent. Refusing
    here is the cheap end of that trade: a blank stamp is caught at ingest time
    instead of surfacing as another car's spec reported VERIFIED at query time.
    """
    text = (value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError(
            'cannot be blank -- name the vehicle these chunks apply to, e.g. '
            '"2014 VW CC 2.0T TSI". Retrieval admits chunks with no vehicle '
            "stamped, so a blank value would make this manual match every car."
        )
    return text


def main():
    ap = argparse.ArgumentParser(description="VAG manual ingestion pipeline (v1)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="report content inventory without writing output")
    pi.add_argument("pdf")
    pi.set_defaults(func=cmd_inspect)

    pg = sub.add_parser("ingest", help="process a manual into chunks/markdown/diagrams")
    pg.add_argument("pdf")
    pg.add_argument("--manual-id", default=None)
    pg.add_argument("--title", default=None)
    pg.add_argument(
        "--vehicle",
        required=True,
        type=_vehicle_arg,
        help='vehicle these chunks apply to, e.g. "2014 VW CC 2.0T TSI", or a '
             'generic marque like "VW (multi-model)" for shared references. '
             "Required -- retrieval scoping fails open on unstamped chunks.",
    )
    pg.add_argument("--engine", default=None)
    pg.add_argument("--year", default=None)
    pg.add_argument("--system", default=None)
    pg.add_argument("--out", default="./out")
    pg.add_argument("--dpi", type=int, default=150)
    pg.add_argument("--max-chars", type=int, default=1800)
    pg.add_argument("--render-all", action="store_true", help="render every page, not just diagram pages")
    pg.add_argument("--no-render", action="store_true", help="skip PNG rendering; record image paths only (text layers only)")
    pg.set_defaults(func=cmd_ingest)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
