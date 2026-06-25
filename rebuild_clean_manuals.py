#!/usr/bin/env python3
"""Rebuild and verify a versioned, fully dewatermarked VAG PDF tree."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz

from dewatermark_pdf import clean_pdf, watermark_form_names
from manual_review import visible_page_text
from vag_pipeline.common import json_dump, now_iso, sha256_file


def semantic_text(value: str) -> list[str]:
    """Comparable content tokens, ignoring PDF extractor spacing artifacts."""
    return re.findall(r"[A-Za-z0-9]+", value.casefold())


def verify_pair(source: Path, clean: Path) -> dict:
    original = fitz.open(source)
    rebuilt = fitz.open(clean)
    errors = []
    if original.page_count != rebuilt.page_count:
        errors.append(
            f"page count changed: {original.page_count} -> {rebuilt.page_count}"
        )
    pages = min(original.page_count, rebuilt.page_count)
    residual_forms = 0
    source_forms = 0
    text_mismatch_pages = 0
    layout_difference_pages = 0
    for index in range(pages):
        source_forms += len(watermark_form_names(original, original[index]))
        residual_forms += len(watermark_form_names(rebuilt, rebuilt[index]))
        original_text = visible_page_text(original[index])
        rebuilt_text = visible_page_text(rebuilt[index])
        if original_text != rebuilt_text:
            layout_difference_pages += 1
        if semantic_text(original_text) != semantic_text(rebuilt_text):
            text_mismatch_pages += 1
    if residual_forms:
        errors.append(f"{residual_forms} watermark forms remain")
    if text_mismatch_pages:
        errors.append(f"readable text differs on {text_mismatch_pages} pages")
    original.close()
    rebuilt.close()
    return {
        "source_pages": pages,
        "clean_pages": pages,
        "residual_watermark_forms": residual_forms,
        "source_watermark_forms": source_forms,
        "readable_text_mismatch_pages": text_mismatch_pages,
        "layout_text_difference_pages": layout_difference_pages,
        "errors": errors,
        "ok": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    source_root = args.source.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    reports = []
    pdfs = sorted(source_root.rglob("*.pdf"))
    for number, source in enumerate(pdfs, 1):
        relative = source.relative_to(source_root)
        clean = output_root / relative
        clean.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{number}/{len(pdfs)}] {relative}", flush=True)
        rebuilt = args.force or not clean.exists()
        if rebuilt:
            forms, glyphs, restored = clean_pdf(
                str(source), str(clean), verbose=False, restore=True
            )
        else:
            forms = glyphs = restored = 0
        verification = verify_pair(source, clean)
        report = {
            "relative_path": str(relative),
            "source_path": str(source),
            "clean_path": str(clean),
            "source_sha256": sha256_file(source),
            "clean_sha256": sha256_file(clean),
            "rebuilt": rebuilt,
            "removed_watermark_forms": forms,
            "removed_fallback_glyphs": glyphs,
            "restored_body_chars": restored,
            **verification,
        }
        reports.append(report)
        status = "OK" if report["ok"] else "FAILED"
        print(
            f"  {status}: {forms} forms removed; "
            f"{report['readable_text_mismatch_pages']} text mismatches",
            flush=True,
        )
        json_dump(
            output_root / "rebuild_manifest.json",
            {
                "schema_version": 1,
                "generated_at": now_iso(),
                "source_root": str(source_root),
                "output_root": str(output_root),
                "total": len(pdfs),
                "completed": len(reports),
                "passed": sum(item["ok"] for item in reports),
                "failed": sum(not item["ok"] for item in reports),
                "manuals": reports,
            },
        )
    failed = [item for item in reports if not item["ok"]]
    print(
        f"Complete: {len(reports) - len(failed)}/{len(reports)} passed; "
        f"{len(failed)} failed",
        flush=True,
    )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
