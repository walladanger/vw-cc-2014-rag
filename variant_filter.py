"""
Engine/gearbox variant filter.

One manual often holds the same job several times, once per engine and
gearbox ("Starter, Removing and Installing, 1.4L TSI Engine, Manual
Transmission", "... 2.0L TSI Engine with DSG Transmission", ...). The chunks
only carry the running page header ("3. Starter"), so search can't tell the
variants apart and may pick the wrong car's procedure.

This module reads each PDF's bookmarks (table of contents) once, finds the
deepest heading that covers a page, and rejects pages whose heading names a
different engine or gearbox than the owner's car.
"""
import bisect
import os
import re

# The owner's car: 2014 CC, 2.0L TSI (CBFA), 6-speed DSG.
OWN_ENGINE = "2.0L TSI"
OWN_GEARBOX = "DSG"

_ENGINE_RE = re.compile(r"\b(1\.4|1\.8|2\.0|3\.6)\s*L?\b(?:\s*(TSI|TDI|FSI))?", re.I)
_OTHER_MODEL_RE = re.compile(r"\b(tiguan|golf|jetta|beetle|eos|touareg|routan|tdi|diesel)\b", re.I)
# Whole manuals for gearboxes the owner's car does not have (it has the 02E DSG).
_OTHER_GEARBOX_MANUALS = ("manual_trans", "09m_auto")
_GEARBOX_RE = re.compile(r"\b(manual transmission|automatic transmission|dsg)\b", re.I)

_toc_cache: dict[str, tuple[list[int], list[str]]] = {}


def _toc(pdf_path: str) -> tuple[list[int], list[str]]:
    if pdf_path in _toc_cache:
        return _toc_cache[pdf_path]
    pages, titles = [], []
    if os.path.isfile(pdf_path):
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            for _level, title, page in doc.get_toc():
                if page > 0:
                    pages.append(page)
                    titles.append(title.strip())
        order = sorted(range(len(pages)), key=lambda i: (pages[i], i))
        pages = [pages[i] for i in order]
        titles = [titles[i] for i in order]
    _toc_cache[pdf_path] = (pages, titles)
    return pages, titles


def heading_for(pdf_path: str, page: int) -> str:
    """Deepest/latest bookmark starting at or before this page."""
    pages, titles = _toc(pdf_path)
    i = bisect.bisect_right(pages, page) - 1
    return titles[i] if i >= 0 else ""


def conflicts(heading: str) -> bool:
    """True when the heading names an engine or gearbox the owner's car doesn't have."""
    for m in _ENGINE_RE.finditer(heading):
        size, kind = m.group(1), (m.group(2) or "").upper()
        if size != "2.0" or kind in ("TDI", "FSI"):
            return True
    if _OTHER_MODEL_RE.search(heading):
        return True
    if re.search(r"\bpassat\b", heading, re.I) and not re.search(r"\bCC\b", heading):
        return True
    for m in _GEARBOX_RE.finditer(heading):
        if m.group(1).lower() != "dsg":
            return True
    return False


def own_variant(heading: str) -> bool:
    """Heading explicitly names the owner's engine (and doesn't conflict)."""
    return bool(re.search(r"2\.0\s*L?\s*TSI", heading, re.I)) and not conflicts(heading)


def apply(results: list[dict], manifests: dict, k: int, chunks: list[dict] | None = None) -> list[dict]:
    """Label each result with its sub-section heading; drop other-variant pages.

    When a result sits in a section written specifically for the owner's car,
    the other pages of that section are pulled in right after it, so a
    multi-page procedure arrives whole instead of one page of it.
    """
    kept, seen, expanded = [], set(), set()

    def _section_pages(manual_id, src, heading):
        return [c for c in chunks or []
                if c["manual_id"] == manual_id and heading_for(src, c["page_physical"]) == heading]

    queue = list(results)
    while queue and len(kept) < k * 2:
        r = queue.pop(0)
        key = r.get("chunk_id") or (r.get("manual_id"), r.get("page_physical"), r.get("text", "")[:40])
        if key in seen:
            continue
        seen.add(key)
        if any(tag in r.get("manual_id", "") for tag in _OTHER_GEARBOX_MANUALS):
            continue
        src = (manifests.get(r.get("manual_id")) or {}).get("source_path", "")
        heading = heading_for(src, r.get("page_physical", 0)) if src else ""
        if r.get("_section_tail"):
            heading = r["_section_tail"]  # first page of the next section; ours ends on it
        if heading and conflicts(heading):
            continue
        if heading:
            r["variant_heading"] = heading
            r["section_title"] = heading
        kept.append(r)
        if heading and own_variant(heading) and (src, heading) not in expanded:
            expanded.add((src, heading))
            section = _section_pages(r["manual_id"], src, heading)
            extra = [dict(c, score=r.get("score", 0), _pulled_in=True) for c in section]
            # A procedure usually finishes at the top of the page where the next
            # section begins, so that page comes along too.
            if section:
                last = max(c["page_physical"] for c in section)
                tail = [c for c in chunks or []
                        if c["manual_id"] == r["manual_id"] and c["page_physical"] == last + 1]
                extra += [dict(c, score=r.get("score", 0), _pulled_in=True, _section_tail=heading)
                          for c in tail[:2]]
            queue = extra + queue
    # Sections written for the owner's exact car go first, in page order.
    own = sorted((r for r in kept if own_variant(r.get("variant_heading", ""))),
                 key=lambda r: (r["manual_id"], r["page_physical"]))
    rest = [r for r in kept if not own_variant(r.get("variant_heading", ""))]
    return (own + rest)[:k]
