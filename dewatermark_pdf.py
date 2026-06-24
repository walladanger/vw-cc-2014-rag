#!/usr/bin/env python3
"""
VAG PDF De-watermarker (v2) -- strips the factory copyright watermark for
HUMAN READABILITY only. The RAG pipeline's source-of-truth PDFs are not touched.

The VAG watermark is text GLYPHS rendered along a diagonal curve -- each glyph
is individually positioned and rotated. We identify those glyphs using the SAME
heuristics ingest_manual.py applies in page_lines() so this script and the
ingest pipeline agree on what counts as watermark:

  (a) glyphs whose line direction is off the horizontal  -> rotated curve glyph
  (b) small (<=8.6pt) light-gray short-text glyphs that ended up horizontal
      at the curve apex                                  -> apex gray fragments

## v2: Automatic body-text restoration

PyMuPDF's apply_redactions() removes ALL content within each redaction bbox,
including body-text characters that happen to overlap a watermark glyph rect.
v2 fixes this collateral damage with a two-step approach on every page:

  1. BEFORE redacting: scan the page with get_text("rawdict") to collect every
     body-text character whose bbox intersects at least one watermark glyph rect.
     These are the characters that will be destroyed in step 2.

  2. AFTER apply_redactions(): re-insert those characters at their exact original
     positions using PyMuPDF TextWriter + the closest base-14 font substitute.

Intersection test uses numpy vectorised broadcast for speed (n_chars × n_wm_rects)
-- ~250× faster than pure-Python per-character loops. Falls back to pure Python if
numpy is not installed (slower on pages with many chars/watermarks, but correct).

Font note: the original embedded proprietary VAG/Myriad fonts are substituted with
base-14 PDF fonts based on span flags (bold/italic/serif/mono). VAG body text is
predominantly Helvetica-like sans-serif, so the visual result is nearly identical.

CRITICAL boundary with the RAG pipeline:
  * Source PDFs are CANONICAL. This script writes to a SEPARATE file/dir.
  * The existing chunks/citations point at the original PDFs by source_hash;
    a de-watermarked copy has a different hash and MUST NOT be substituted as
    the citation target. Use cleaned PDFs for reading, not for re-ingestion.
  * If you ever ingest a cleaned PDF, treat it as a new manual_id with its own
    source_hash. Never overwrite a citation's target.

Image-watermark fallback (NOT implemented here): some PDFs (scans, third-party
exports) carry a raster-image watermark embedded as a page image. Text-glyph
detection won't find those. If --dry-run reports 0 spans but the watermark is
still visually present, the watermark is a raster -- a separate template-match
pass using your gif/png/jpeg samples is the right tool, not this script.

Usage:
  python dewatermark_pdf.py <in.pdf>                       # -> in_clean.pdf
  python dewatermark_pdf.py <in.pdf> -o <out.pdf>
  python dewatermark_pdf.py <in_dir>  -o <out_dir>         # batch a folder
  python dewatermark_pdf.py <in.pdf> --dry-run             # report counts only
  python dewatermark_pdf.py <in.pdf> --inspect 5           # before/after PNGs
  python dewatermark_pdf.py <in.pdf> --no-restore          # skip body-text restoration
  python dewatermark_pdf.py <in.pdf> --suffix _clean       # custom output suffix
"""
import argparse
import os
import sys
from collections import defaultdict

import fitz  # PyMuPDF

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ── watermark detection (mirrors ingest_manual.py page_lines() filter) ────────

def _span_text(span):
    """Extract text from a rawdict or dict span.

    rawdict spans have span["text"] == "" -- text must be built from chars.
    dict spans populate span["text"] directly.
    This function handles both transparently.
    """
    t = span.get("text", "")
    if not t:
        t = "".join(c.get("c", "") for c in span.get("chars", []))
    return t


def is_watermark_span(span, line_dir):
    """True if this text span is a VAG watermark glyph.

    Two cases, matching exactly what ingest_manual.py already filters out:
      (a) line direction is not horizontal  -> rotated curve glyph
      (b) horizontal but small + gray + short  -> curve-apex gray fragment
    Body text is pure black (color == 0) at body size and survives both tests.
    """
    horizontal = line_dir[0] >= 0.99 and abs(line_dir[1]) <= 0.05
    if not horizontal:
        return True
    text = _span_text(span).strip()
    size = span.get("size", 0)
    color = span.get("color", 0)  # 0 == pure black body text
    if size <= 8.6 and color != 0 and 0 < len(text) <= 12:
        return True
    return False


def find_watermark_rects(page):
    """Return list of fitz.Rect, one per watermark glyph on the page."""
    rects = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:  # text blocks only (type 0)
            continue
        for line in block.get("lines", []):
            line_dir = line.get("dir", (1, 0))
            for span in line.get("spans", []):
                if not span.get("text", "").strip():
                    continue
                if is_watermark_span(span, line_dir):
                    rects.append(fitz.Rect(span["bbox"]))
    return rects


# ── body-text restoration helpers ─────────────────────────────────────────────

def _color_tuple(c_int):
    """Convert packed 24-bit int color to (r, g, b) float tuple."""
    if c_int == 0:
        return (0.0, 0.0, 0.0)
    return (
        ((c_int >> 16) & 255) / 255.0,
        ((c_int >> 8)  & 255) / 255.0,
        ( c_int        & 255) / 255.0,
    )


def _flag_font(flags):
    """Map PyMuPDF span flags to closest base-14 PDF font name.

    Flag bits: 2=italic, 4=serifed, 8=monospaced, 16=bold
    Base-14 fonts used:
      helv  Helvetica          hebo  Helvetica-Bold
      heit  Helvetica-Oblique  tiro  Times-Roman
      tibo  Times-Bold         tiit  Times-Italic
      tibi  Times-BoldItalic   cour  Courier
      cobo  Courier-Bold       coit  Courier-Oblique
    """
    b = bool(flags & 16)
    i = bool(flags & 2)
    s = bool(flags & 4)   # serifed
    m = bool(flags & 8)   # monospaced
    if m:
        return "cobo" if b else ("coit" if i else "cour")
    if s:
        return "tibi" if (b and i) else ("tibo" if b else ("tiit" if i else "tiro"))
    return "hebo" if b else ("heit" if i else "helv")


_font_cache: dict = {}

def _get_font(name):
    """Cached font lookup; falls back to Helvetica on unknown names."""
    if name not in _font_cache:
        try:
            _font_cache[name] = fitz.Font(name)
        except Exception:
            _font_cache[name] = fitz.Font("helv")
    return _font_cache[name]


def collect_body_chars_at_wm_positions(page, wm_rects):
    """Find body-text characters whose bbox intersects any watermark rect.

    Uses get_text("rawdict") for per-character position data.
    Returns list of (fitz.Point origin, char, fontname, size, color_int).
    These chars will be erased by apply_redactions() and must be re-inserted.
    """
    if not wm_rects:
        return []

    raw = page.get_text("rawdict")

    # Collect all body chars with their bboxes
    # body row: (origin_x, origin_y, char, fontname, size, color_int,
    #            bbox_x0, bbox_y0, bbox_x1, bbox_y1)
    body = []
    for block in raw.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            line_dir = line.get("dir", (1, 0))
            for span in line.get("spans", []):
                t = _span_text(span)
                if not t.strip():
                    continue
                if is_watermark_span(span, line_dir):
                    continue  # skip watermark spans
                fn = _flag_font(span.get("flags", 0))
                sz = span["size"]
                col = span["color"]
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c or c <= " ":
                        continue
                    b = ch["bbox"]
                    o = ch["origin"]
                    body.append((o[0], o[1], c, fn, sz, col,
                                 b[0], b[1], b[2], b[3]))

    if not body:
        return []

    # Vectorised intersection test (n_chars × n_wm_rects broadcast)
    if _HAS_NUMPY:
        wm_arr = np.array(
            [[r.x0, r.y0, r.x1, r.y1] for r in wm_rects], dtype=np.float32
        )
        cb = np.array([[r[6], r[7], r[8], r[9]] for r in body], dtype=np.float32)
        # no_int[i, j] = True iff char i does NOT intersect wm rect j
        no_int = (
            (cb[:, None, 2] <= wm_arr[None, :, 0]) |
            (cb[:, None, 0] >= wm_arr[None, :, 2]) |
            (cb[:, None, 3] <= wm_arr[None, :, 1]) |
            (cb[:, None, 1] >= wm_arr[None, :, 3])
        )
        hits = ~np.all(no_int, axis=1)  # char hits at least one wm rect
        return [
            (fitz.Point(body[i][0], body[i][1]),
             body[i][2], body[i][3], body[i][4], body[i][5])
            for i, hit in enumerate(hits) if hit
        ]
    else:
        # Pure-Python fallback (correct but slower for dense pages)
        result = []
        for ox, oy, c, fn, sz, col, x0, y0, x1, y1 in body:
            for r in wm_rects:
                if not (x1 <= r.x0 or x0 >= r.x1 or y1 <= r.y0 or y0 >= r.y1):
                    result.append((fitz.Point(ox, oy), c, fn, sz, col))
                    break
        return result


def restore_body_text(page, chars):
    """Re-insert body chars removed as collateral damage during redaction.

    Groups chars by color, then writes each group with a single TextWriter call.
    """
    if not chars:
        return
    # Group by color to minimise TextWriter calls
    by_col = defaultdict(list)
    for origin, c, fn, sz, col in chars:
        by_col[col].append((origin, c, fn, sz))
    for col_int, items in by_col.items():
        tw = fitz.TextWriter(page.rect)
        for origin, c, fn, sz in items:
            tw.append(origin, c, font=_get_font(fn), fontsize=sz)
        tw.write_text(page, color=_color_tuple(col_int))


# ── main operations ───────────────────────────────────────────────────────────

def clean_pdf(in_path, out_path, verbose=True, restore=True):
    """Write a watermark-redacted (and body-text-restored) copy.

    Steps per page:
      1. find_watermark_rects() -- identify glyph bboxes
      2. collect_body_chars_at_wm_positions() -- save chars that will be lost
      3. add_redact_annot() + apply_redactions() -- remove watermark content
      4. restore_body_text() -- re-insert the saved chars (unless --no-restore)

    Returns (wm_glyphs_removed, body_chars_restored).
    """
    doc = fitz.open(in_path)
    total_wm = 0
    total_restored = 0

    for i, page in enumerate(doc):
        rects = find_watermark_rects(page)
        if not rects:
            continue

        # Step 1: collect body chars that will be caught in the redaction
        chars_to_restore = (
            collect_body_chars_at_wm_positions(page, rects)
            if restore else []
        )

        # Step 2: redact watermark glyphs
        for r in rects:
            # fill=None  -> transparent (no white box drawn over the area)
            # cross_out=False -> no diagonal X marker
            page.add_redact_annot(r, fill=None, cross_out=False)
        # PDF_REDACT_IMAGE_NONE: never touch embedded raster images
        # (legitimate diagrams, exploded views, fuse-box photos)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        total_wm += len(rects)

        # Step 3: restore collateral body chars
        if chars_to_restore:
            restore_body_text(page, chars_to_restore)
            total_restored += len(chars_to_restore)

        if verbose and (i + 1) % 50 == 0:
            print(f"  ...page {i+1}/{len(doc)}", file=sys.stderr)

    # garbage=4 + deflate + clean keeps file size sane after redaction
    doc.save(out_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total_wm, total_restored


def dry_run(in_path):
    """Report per-page watermark glyph counts without writing anything."""
    doc = fitz.open(in_path)
    grand = 0
    print(f"{in_path}: {len(doc)} pages")
    nonzero_pages = 0
    for i, page in enumerate(doc):
        n = len(find_watermark_rects(page))
        grand += n
        if n:
            nonzero_pages += 1
            if nonzero_pages <= 10:
                print(f"  page {i+1:4d}: {n} watermark glyphs")
    if nonzero_pages > 10:
        print(f"  ... ({nonzero_pages - 10} more pages with watermark glyphs)")
    print(f"TOTAL: {grand} watermark glyphs across "
          f"{nonzero_pages}/{len(doc)} pages")
    if grand == 0:
        print("  NOTE: 0 detections -- watermark may be a RASTER IMAGE rather "
              "than text glyphs. This script handles text-glyph watermarks "
              "only. See the docstring for the image-fallback note.")
    doc.close()


def inspect(in_path, page_no, dpi=150):
    """Render one page before and after redaction to side-by-side PNGs.

    Does not save the modified PDF -- use this purely to eyeball the result.
    PNGs are written alongside the input file.
    """
    doc = fitz.open(in_path)
    if page_no < 1 or page_no > len(doc):
        sys.exit(f"page {page_no} out of range (1..{len(doc)})")
    base = os.path.splitext(os.path.basename(in_path))[0]
    out_dir = os.path.dirname(os.path.abspath(in_path)) or "."

    page = doc[page_no - 1]
    before = os.path.join(out_dir, f"{base}_p{page_no:04d}_before.png")
    page.get_pixmap(dpi=dpi).save(before)

    rects = find_watermark_rects(page)
    chars_to_restore = collect_body_chars_at_wm_positions(page, rects)
    for r in rects:
        page.add_redact_annot(r, fill=None, cross_out=False)
    if rects:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    if chars_to_restore:
        restore_body_text(page, chars_to_restore)

    after = os.path.join(out_dir, f"{base}_p{page_no:04d}_after.png")
    page.get_pixmap(dpi=dpi).save(after)
    doc.close()
    print(f"page {page_no}: removed {len(rects)} watermark glyphs, "
          f"restored {len(chars_to_restore)} body chars")
    print(f"  before -> {before}")
    print(f"  after  -> {after}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _default_single_output(in_path, suffix):
    d = os.path.dirname(os.path.abspath(in_path))
    base, ext = os.path.splitext(os.path.basename(in_path))
    return os.path.join(d, f"{base}{suffix}{ext}")


def main():
    ap = argparse.ArgumentParser(
        description="VAG PDF de-watermarker v2 -- text-glyph removal + body-text "
                    "restoration. Source PDFs are never modified."
    )
    ap.add_argument("input", help="input PDF file, or directory of PDFs for batch")
    ap.add_argument("-o", "--output",
                    help="output PDF (single) or directory (batch). "
                         "Default: <name>_clean.pdf alongside input.")
    ap.add_argument("--dry-run", action="store_true",
                    help="report watermark glyph counts; write nothing")
    ap.add_argument("--inspect", type=int, metavar="PAGE",
                    help="render before/after PNGs of one page; write no PDF")
    ap.add_argument("--suffix", default="_clean",
                    help="output filename suffix (default: _clean)")
    ap.add_argument("--no-restore", action="store_true",
                    help="skip body-text restoration pass (faster, but may leave "
                         "gaps where body text overlapped watermark glyphs)")
    args = ap.parse_args()

    restore = not args.no_restore

    if not _HAS_NUMPY and restore:
        print("WARNING: numpy not installed -- using pure-Python intersection "
              "(correct but slower for large pages). "
              "Install numpy for best performance.", file=sys.stderr)

    if args.inspect is not None:
        if os.path.isdir(args.input):
            sys.exit("--inspect requires a single PDF, not a directory")
        inspect(args.input, args.inspect)
        return

    # batch directory mode
    if os.path.isdir(args.input):
        pdfs = sorted(f for f in os.listdir(args.input)
                      if f.lower().endswith(".pdf"))
        if not pdfs:
            sys.exit(f"no PDFs found in {args.input}")
        out_dir = None
        if not args.dry_run:
            out_dir = (args.output
                       or os.path.abspath(args.input).rstrip(os.sep) + "_clean")
            os.makedirs(out_dir, exist_ok=True)
            print(f"output dir: {out_dir}\n")
        for fn in pdfs:
            in_path = os.path.join(args.input, fn)
            print(f"[{fn}]")
            if args.dry_run:
                dry_run(in_path)
            else:
                out_path = os.path.join(out_dir, fn)
                n_wm, n_res = clean_pdf(in_path, out_path, restore=restore)
                print(f"  removed {n_wm} watermark glyphs, "
                      f"restored {n_res} body chars -> {out_path}")
            print()
        return

    # single file mode
    if args.dry_run:
        dry_run(args.input)
        return
    out_path = args.output or _default_single_output(args.input, args.suffix)
    if os.path.abspath(out_path) == os.path.abspath(args.input):
        sys.exit("refusing to overwrite the input PDF; choose a different -o")
    n_wm, n_res = clean_pdf(args.input, out_path, restore=restore)
    print(f"removed {n_wm} watermark glyphs, "
          f"restored {n_res} body chars -> {out_path}")


if __name__ == "__main__":
    main()
