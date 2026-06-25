#!/usr/bin/env python3
"""Local side-by-side PDF integrity review and correction editor."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import fitz
from flask import Blueprint, Flask, abort, jsonify, render_template, request, send_file

from vag_pipeline.common import json_dump, now_iso

DOC_CODE = re.compile(r"^([A-Z0-9]{10,12})", re.IGNORECASE)
ORIGINAL_PRIORITIES = (
    "official vw manuuals",
    "unprocessed vw cc manuals",
    "vw cc clean",
    "processed vw cc manuals",
)
CLEAN_PRIORITIES = (
    "projects\\vw cc clean rebuilt v3",
    "projects\\vw cc clean",
)


def register_manual_review(
    app: Flask,
    corpus: Path,
    search_root: Path,
    url_prefix: str = "/manual-review",
) -> Blueprint:
    review = Blueprint("manual_review", __name__, url_prefix=url_prefix)
    app.json.ensure_ascii = True
    corpus = corpus.resolve()
    review_dir = corpus / ".manual_review"
    corrections_dir = review_dir / "corrections"
    corrections_dir.mkdir(parents=True, exist_ok=True)
    index_path = review_dir / "review_index.json"

    def load_index(force: bool = False) -> dict:
        if force or not index_path.exists():
            build_review_index(corpus, search_root, index_path)
        return json.loads(index_path.read_text(encoding="utf-8"))

    def manual(manual_id: str) -> dict:
        for item in load_index()["manuals"]:
            if item["manual_id"] == manual_id:
                return item
        abort(404)

    @review.get("/")
    def home():
        return render_template("manual_review.html", review_base=url_prefix.rstrip("/"))

    @review.get("/api/manuals")
    def manuals():
        return jsonify(load_index())

    @review.post("/api/rebuild-index")
    def rebuild_index():
        return jsonify(load_index(force=True))

    @review.get("/api/manual/<manual_id>")
    def manual_detail(manual_id: str):
        item = manual(manual_id)
        correction_path = corrections_dir / f"{manual_id}.json"
        corrections = (
            json.loads(correction_path.read_text(encoding="utf-8"))
            if correction_path.exists()
            else {"pages": {}}
        )
        return jsonify({"manual": item, "corrections": corrections})

    @review.get("/api/page/<manual_id>/<kind>/<int:page>.png")
    def page_image(manual_id: str, kind: str, page: int):
        item = manual(manual_id)
        if kind not in {"original", "processed"}:
            abort(404)
        path = Path(
            item["original_path"]
            if kind == "original"
            else item.get("clean_path", item["processed_path"])
        )
        if not path.exists():
            abort(404)
        document = open_document(str(path))
        rendered_page = (
            page + item.get("original_page_offset", 0)
            if kind == "original"
            else page
        )
        if rendered_page < 1 or rendered_page > document.page_count:
            abort(404)
        zoom = min(max(float(request.args.get("zoom", "1.35")), 0.7), 2.5)
        pixmap = document[rendered_page - 1].get_pixmap(
            matrix=fitz.Matrix(zoom, zoom), alpha=False
        )
        response = send_file(
            io.BytesIO(pixmap.tobytes("png")),
            mimetype="image/png",
            download_name=f"{manual_id}-{kind}-{page}.png",
        )
        response.headers["Cache-Control"] = "private, max-age=86400"
        return response

    @review.get("/api/page/<manual_id>/<int:page>")
    def page_data(manual_id: str, page: int):
        item = manual(manual_id)
        if page < 1 or page > item["review_pages"]:
            abort(404)
        chunks = page_chunks(corpus / item["relative_dir"] / "chunks.jsonl", page)
        original_text = pdf_page_text(
            Path(item["original_path"]),
            page + item.get("original_page_offset", 0),
        )
        processed_text = pdf_page_text(
            Path(item.get("clean_path", item["processed_path"])), page
        )
        extracted_text = "\n\n".join(
            chunk.get("text", "") for chunk in chunks if chunk.get("text")
        ).strip()
        correction_path = corrections_dir / f"{manual_id}.json"
        corrections = (
            json.loads(correction_path.read_text(encoding="utf-8"))
            if correction_path.exists()
            else {"pages": {}}
        )
        saved = corrections.get("pages", {}).get(str(page), {})
        page_audit = item.get("page_audit", {}).get(str(page), {})
        return jsonify(
            {
                "page": page,
                "original_text": original_text,
                "processed_text": processed_text,
                "extracted_text": extracted_text,
                "editable_text": saved.get("corrected_text", extracted_text),
                "note": saved.get("note", ""),
                "status": saved.get("status", page_audit.get("status", "unreviewed")),
                "counts": {
                    "original": len(original_text),
                    "processed": len(processed_text),
                    "extracted": len(extracted_text),
                },
                "flags": {
                    **page_audit,
                    "has_diagram": any(chunk.get("has_diagram") for chunk in chunks),
                    "needs_ocr": any(chunk.get("needs_ocr") for chunk in chunks),
                },
                "chunks": [
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "section_title": chunk.get("section_title"),
                        "char_count": len(chunk.get("text", "")),
                    }
                    for chunk in chunks
                ],
            }
        )

    @review.post("/api/page/<manual_id>/<int:page>")
    def save_page(manual_id: str, page: int):
        item = manual(manual_id)
        if page < 1 or page > item["review_pages"]:
            abort(404)
        payload = request.get_json(force=True)
        status = payload.get("status", "needs_review")
        if status not in {"unreviewed", "needs_review", "edited", "approved"}:
            abort(400)
        path = corrections_dir / f"{manual_id}.json"
        value = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"manual_id": manual_id, "pages": {}}
        )
        value["updated_at"] = now_iso()
        value["pages"][str(page)] = {
            "status": status,
            "corrected_text": str(payload.get("corrected_text", "")),
            "note": str(payload.get("note", "")),
            "updated_at": now_iso(),
        }
        json_dump(path, value)
        return jsonify({"ok": True, "saved": value["pages"][str(page)]})

    @review.get("/api/export-corrections")
    def export_corrections():
        rows = []
        for path in sorted(corrections_dir.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            for page, correction in value.get("pages", {}).items():
                rows.append(
                    {
                        "manual_id": value.get("manual_id", path.stem),
                        "page_physical": int(page),
                        **correction,
                    }
                )
        output = review_dir / "manual_corrections.json"
        json_dump(output, {"generated_at": now_iso(), "corrections": rows})
        return send_file(output, as_attachment=True)

    app.register_blueprint(review)
    return review


def create_app(corpus: Path, search_root: Path) -> Flask:
    app = Flask(__name__)
    register_manual_review(app, corpus, search_root, url_prefix="")
    return app


@lru_cache(maxsize=12)
def open_document(path: str) -> fitz.Document:
    return fitz.open(path)


def pdf_page_text(path: Path, page: int) -> str:
    if not path.exists():
        return ""
    document = open_document(str(path))
    if page < 1 or page > document.page_count:
        return ""
    return visible_page_text(document[page - 1])


def page_chunks(path: Path, page: int) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            physical = chunk.get("page_physical") or chunk.get("page_start")
            if physical == page:
                rows.append(chunk)
    return rows


def chunks_by_page(path: Path) -> dict[int, list[dict]]:
    pages: dict[int, list[dict]] = {}
    if not path.exists():
        return pages
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            physical = chunk.get("page_physical") or chunk.get("page_start")
            if isinstance(physical, int):
                pages.setdefault(physical, []).append(chunk)
    return pages


def document_code(path: Path) -> str:
    match = DOC_CODE.match(path.name)
    return match.group(1).upper() if match else ""


def normalized_filename(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def resolve_source(path: Path) -> Path:
    if path.exists():
        return path.resolve()
    if path.parent.exists():
        expected = normalized_filename(path.stem)
        matches = sorted(
            path.parent.glob("*.pdf"),
            key=lambda candidate: (
                normalized_filename(candidate.stem) != expected,
                abs(len(candidate.stem) - len(path.stem)),
            ),
        )
        for candidate in matches:
            if normalized_filename(candidate.stem) == expected:
                return candidate.resolve()
    return path.resolve()


def candidate_score(path: Path) -> tuple[int, int, int]:
    lowered = str(path).lower()
    priority = next(
        (index for index, marker in enumerate(ORIGINAL_PRIORITIES) if marker in lowered),
        len(ORIGINAL_PRIORITIES),
    )
    altered = int(
        any(
            token in path.name.lower()
            for token in ("reversed", "trimmed", "stripped", "watermark")
        )
    )
    return priority, altered, len(str(path))


def visible_page_text(page: fitz.Page) -> str:
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if direction[0] < 0.99 or abs(direction[1]) > 0.05:
                continue
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            max_size = max((span.get("size", 0) for span in spans), default=0)
            entirely_gray = all(span.get("color", 0) != 0 for span in spans)
            if max_size <= 8.6 and entirely_gray and len(text) <= 12:
                continue
            lines.append(text)
    return "\n".join(lines).strip()


def token_set(page: fitz.Page) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]{3,}", visible_page_text(page))
        if not token.isdigit()
    }


def infer_page_offset(original: fitz.Document, processed: fitz.Document) -> int:
    if original.name and original.name == processed.name:
        return 0
    maximum = min(15, max(0, original.page_count - 1))
    sample_indexes = [
        index
        for index in sorted(
        {
            0,
            1,
            2,
            min(10, processed.page_count - 1),
            processed.page_count // 2,
            max(0, processed.page_count - 2),
        }
        )
        if index < processed.page_count
    ]
    best_offset = 0
    best_score = -1.0
    for offset in range(maximum + 1):
        scores = []
        for processed_index in sample_indexes:
            original_index = processed_index + offset
            if original_index >= original.page_count:
                continue
            left = token_set(original[original_index])
            right = token_set(processed[processed_index])
            if not left and not right:
                scores.append(1.0)
            elif left and right:
                scores.append(len(left & right) / len(left | right))
        score = sum(scores) / len(scores) if scores else 0.0
        if score > best_score:
            best_score = score
            best_offset = offset
    return best_offset


def find_original(processed: Path, candidates: dict[str, list[Path]]) -> Path:
    code = document_code(processed)
    if not code:
        return processed
    matches = [path for path in candidates.get(code, []) if path != processed]
    return sorted(matches, key=candidate_score)[0] if matches else processed


def find_clean_copy(processed: Path, candidates: dict[str, list[Path]]) -> Path:
    code = document_code(processed)
    if not code:
        return processed
    matches = candidates.get(code, [])
    for marker in CLEAN_PRIORITIES:
        clean = [path for path in matches if marker in str(path).lower()]
        if clean:
            return sorted(clean, key=lambda path: len(str(path)))[0]
    return processed


def build_review_index(corpus: Path, search_root: Path, destination: Path) -> dict:
    manifests = sorted(corpus.rglob("manifest.json"))
    codes = set()
    manifest_values = []
    for path in manifests:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        processed = Path(value.get("source_path", ""))
        code = document_code(processed)
        if code:
            codes.add(code)
        manifest_values.append((path, value, processed))

    candidates: dict[str, list[Path]] = {code: [] for code in codes}
    for path in search_root.rglob("*.pdf"):
        code = document_code(path)
        if code in candidates:
            candidates[code].append(path.resolve())

    manuals = []
    for manifest_path, manifest, processed in manifest_values:
        processed = resolve_source(processed)
        original = find_original(processed, candidates)
        clean_copy = (
            processed
            if manifest.get("manual_id", "").startswith("autodoc_")
            else find_clean_copy(processed, candidates)
        )
        processed_doc = fitz.open(clean_copy)
        original_doc = fitz.open(original)
        processed_pages = processed_doc.page_count
        original_pages = original_doc.page_count
        original_page_offset = infer_page_offset(original_doc, processed_doc)
        review_pages = processed_pages
        manual_chunks = chunks_by_page(manifest_path.parent / "chunks.jsonl")
        page_audit = {}
        missing_candidates = 0
        pdf_loss_candidates = 0
        extraction_candidates = 0
        for page_index in range(review_pages):
            original_index = page_index + original_page_offset
            original_chars = (
                len(visible_page_text(original_doc[original_index]))
                if original_index < original_pages
                else 0
            )
            processed_chars = (
                len(visible_page_text(processed_doc[page_index]))
                if page_index < processed_pages
                else 0
            )
            ratio = (
                processed_chars / original_chars
                if original_chars
                else (1.0 if processed_chars == 0 else 2.0)
            )
            extracted_chars = sum(
                len(chunk.get("text", "")) for chunk in manual_chunks.get(page_index + 1, [])
            )
            extracted_ratio = (
                extracted_chars / processed_chars
                if processed_chars
                else (1.0 if extracted_chars == 0 else 2.0)
            )
            possible_pdf_loss = original_chars >= 80 and ratio < 0.7
            possible_extraction_loss = (
                processed_chars >= 120 and extracted_ratio < 0.45
            )
            possible_missing = possible_pdf_loss or possible_extraction_loss
            if possible_missing:
                missing_candidates += 1
            if possible_pdf_loss:
                pdf_loss_candidates += 1
            if possible_extraction_loss:
                extraction_candidates += 1
            page_audit[str(page_index + 1)] = {
                "original_chars": original_chars,
                "processed_chars": processed_chars,
                "extracted_chars": extracted_chars,
                "processed_ratio": round(ratio, 3),
                "extracted_ratio": round(extracted_ratio, 3),
                "possible_pdf_text_loss": possible_pdf_loss,
                "possible_extraction_loss": possible_extraction_loss,
                "possible_missing_text": possible_missing,
                "status": "needs_review" if possible_missing else "unreviewed",
            }
        processed_doc.close()
        original_doc.close()
        source_kind = (
            "same_source"
            if original == processed
            else (
                "official_original"
                if "official vw manuuals" in str(original).lower()
                else "matched_copy"
            )
        )
        manuals.append(
            {
                "manual_id": manifest.get("manual_id", manifest_path.parent.name),
                "title": manifest.get("manual_title", manifest_path.parent.name),
                "relative_dir": str(manifest_path.parent.relative_to(corpus)),
                "processed_path": str(processed),
                "processed_filename": clean_copy.name,
                "clean_path": str(clean_copy),
                "indexed_source_path": str(processed),
                "indexed_source_filename": processed.name,
                "original_path": str(original),
                "original_filename": original.name,
                "source_kind": source_kind,
                "clean_copy_kind": (
                    "clean_reading_copy"
                    if clean_copy != processed
                    else "indexed_source"
                ),
                "review_type": (
                    "community_extraction"
                    if manifest.get("manual_id", "").startswith("autodoc_")
                    else "factory_integrity"
                ),
                "processed_pages": processed_pages,
                "original_pages": original_pages,
                "review_pages": review_pages,
                "original_page_offset": original_page_offset,
                "chunk_count": manifest.get("chunk_count", 0),
                "diagram_pages": manifest.get("diagram_pages", []),
                "needs_ocr_pages": manifest.get("needs_ocr_pages", []),
                "possible_missing_pages": missing_candidates,
                "possible_pdf_loss_pages": pdf_loss_candidates,
                "possible_extraction_pages": extraction_candidates,
                "page_audit": page_audit,
                "application": manifest.get("applicability", {}),
            }
        )
    value = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "corpus": str(corpus),
        "manual_count": len(manuals),
        "official_matches": sum(
            item["source_kind"] == "official_original" for item in manuals
        ),
        "same_source": sum(item["source_kind"] == "same_source" for item in manuals),
        "factory_manuals": sum(
            item["review_type"] == "factory_integrity" for item in manuals
        ),
        "community_guides": sum(
            item["review_type"] == "community_extraction" for item in manuals
        ),
        "possible_missing_pages": sum(
            item["possible_missing_pages"] for item in manuals
        ),
        "possible_pdf_loss_pages": sum(
            item["possible_pdf_loss_pages"] for item in manuals
        ),
        "possible_extraction_pages": sum(
            item["possible_extraction_pages"] for item in manuals
        ),
        "manuals": manuals,
    }
    json_dump(destination, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(
            os.getenv(
                "VW_RAG_OUT",
                r"C:\Users\Desktop\OneDrive\Documents\Projects\vw_rag_phase2b\out",
            )
        ),
    )
    parser.add_argument(
        "--search-root",
        type=Path,
        default=Path(r"C:\Users\Desktop\OneDrive"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5074)
    parser.add_argument("--rebuild-index", action="store_true")
    args = parser.parse_args()
    app = create_app(args.corpus, args.search_root)
    if args.rebuild_index:
        with app.test_client() as client:
            client.post("/api/rebuild-index")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
