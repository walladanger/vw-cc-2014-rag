from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BenchmarkTarget:
    role: str
    match: str
    description: str
    member_name: str = ""


DEFAULT_TARGETS = (
    BenchmarkTarget("brake", "D3E8012ED5C-Brake_System", "Brake repair manual with procedures, PR codes, warnings and diagrams"),
    BenchmarkTarget("engine", "D3E80480D47-4-Cylinder_Direct_Injection", "1.8L/2.0L turbo chain-drive engine manual"),
    BenchmarkTarget("wiring", "K0059040021-Wiring_Diagrams_and_Component_Locations", "Wiring diagrams and component locations"),
)

EXTERNAL_PIPELINES = (
    "ragflow",
    "nemo-retriever",
    "nvidia-rag-blueprint",
)

EXTERNAL_REQUIRED_FIELDS = (
    "status",
    "source_sha256",
    "page_count",
    "pages_with_text",
    "diagram_pages",
    "rendered_pages",
    "page_anchored",
    "section_hierarchy",
    "warnings_detected",
    "tables_detected",
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_benchmark_manuals(zip_path: str | os.PathLike[str], targets: Iterable[BenchmarkTarget] = DEFAULT_TARGETS) -> dict[str, BenchmarkTarget]:
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
    found: dict[str, BenchmarkTarget] = {}
    for target in targets:
        matches = [m for m in members if target.match.lower() in Path(m).name.lower()]
        if not matches:
            raise ValueError(f"Missing benchmark manual for role '{target.role}' matching '{target.match}'")
        if len(matches) > 1:
            matches.sort(key=lambda x: ("reversed_trimmed_reversed" not in x.lower(), len(x), x.lower()))
        found[target.role] = BenchmarkTarget(target.role, target.match, target.description, matches[0])
    return found


def _safe_destination(root: Path, member_name: str) -> Path:
    root = root.resolve()
    dest = (root / member_name).resolve()
    if dest != root and root not in dest.parents:
        raise ValueError(f"unsafe zip member: {member_name}")
    return dest


def safe_extract_members(zip_path: str | os.PathLike[str], members: Iterable[str], output_dir: str | os.PathLike[str]) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as zf:
        available = set(zf.namelist())
        for member_name in members:
            if member_name not in available:
                raise ValueError(f"zip member not found: {member_name}")
            dest = _safe_destination(output_dir, member_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member_name) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted[member_name] = dest
    return extracted


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    pages = max(0, int(result.get("page_count") or 0))
    text_pages = max(0, int(result.get("pages_with_text") or 0))
    diagram_pages = max(0, int(result.get("diagram_pages") or 0))
    rendered_pages = max(0, int(result.get("rendered_pages") or 0))
    text_ratio = round(text_pages / pages, 4) if pages else 0.0
    visual_ratio = round(min(rendered_pages, diagram_pages) / diagram_pages, 4) if diagram_pages else 1.0
    provenance_ok = bool(result.get("source_sha256")) and bool(result.get("page_anchored"))
    structure = 1.0 if result.get("section_hierarchy") else 0.0
    warning_signal = 1.0 if int(result.get("warnings_detected") or 0) > 0 else 0.0
    table_signal = 1.0 if int(result.get("tables_detected") or 0) > 0 else 0.5
    quality = round(
        0.30 * text_ratio
        + 0.30 * visual_ratio
        + 0.20 * (1.0 if provenance_ok else 0.0)
        + 0.10 * structure
        + 0.05 * warning_signal
        + 0.05 * table_signal,
        4,
    )
    return {
        "text_coverage_ratio": text_ratio,
        "visual_preservation_ratio": visual_ratio,
        "provenance_ok": provenance_ok,
        "quality_score": quality,
    }


def normalize_external_result(pipeline: str, pdf_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    if pipeline not in EXTERNAL_PIPELINES:
        raise ValueError(f"Unsupported external benchmark pipeline: {pipeline}")
    if result.get("status") != "ok":
        raise ValueError(f"External result for {pipeline} must use status='ok'")

    missing = [field for field in EXTERNAL_REQUIRED_FIELDS if field not in result]
    if missing:
        raise ValueError(f"External result for {pipeline} is missing fields: {', '.join(missing)}")

    expected_hash = sha256_file(pdf_path)
    if result.get("source_sha256") != expected_hash:
        raise ValueError(
            f"External result source_sha256 does not match benchmark PDF for {pipeline}: "
            f"expected {expected_hash}, got {result.get('source_sha256')}"
        )

    normalized = dict(result)
    normalized["pipeline"] = pipeline
    normalized.setdefault("elapsed_seconds", None)
    normalized.setdefault("text_chars", None)
    normalized.setdefault("headings_detected", None)
    normalized.setdefault("rag_eval", {})
    normalized.update(summarize_result(normalized))
    return normalized


def build_external_job_manifest(
    targets: dict[str, BenchmarkTarget],
    extracted: dict[str, Path],
    output_dir: str | os.PathLike[str],
) -> Path:
    output_dir = Path(output_dir).resolve()
    result_root = output_dir / "external-results"
    jobs = []
    for role, target in targets.items():
        pdf_path = extracted[target.member_name].resolve()
        source_hash = sha256_file(pdf_path)
        for pipeline in EXTERNAL_PIPELINES:
            jobs.append({
                "role": role,
                "pipeline": pipeline,
                "input_pdf": str(pdf_path),
                "source_sha256": source_hash,
                "result_path": str((result_root / role / f"{pipeline}.json").resolve()),
                "required_result_fields": list(EXTERNAL_REQUIRED_FIELDS),
                "optional_rag_eval_fields": [
                    "context_precision",
                    "context_recall",
                    "faithfulness",
                    "answer_relevancy",
                    "citation_precision",
                ],
            })
    payload = {
        "schema_version": 1,
        "pipelines": list(EXTERNAL_PIPELINES),
        "jobs": jobs,
    }
    manifest_path = output_dir / "external-jobs.json"
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _load_external_result(
    pipeline: str,
    role: str,
    pdf_path: Path,
    external_results_dir: Path | None,
) -> dict[str, Any]:
    expected_path = (
        external_results_dir / role / f"{pipeline}.json"
        if external_results_dir is not None
        else None
    )
    if expected_path is None or not expected_path.is_file():
        return {
            "pipeline": pipeline,
            "status": "skipped",
            "reason": "External result not supplied. Run the job from external-jobs.json and write the normalized JSON result to the requested result_path.",
            "source_sha256": sha256_file(pdf_path),
            "expected_result_path": str(expected_path) if expected_path else None,
        }
    payload = json.loads(expected_path.read_text(encoding="utf-8"))
    return normalize_external_result(pipeline, pdf_path, payload)


def _baseline_metrics(pdf_path: Path, render_dir: Path | None = None, render_dpi: int = 120) -> dict[str, Any]:
    import fitz

    try:
        from ingest_manual import detect_body_size, diagram_profile, is_heading, page_lines
    except Exception:
        detect_body_size = diagram_profile = is_heading = page_lines = None

    started = time.perf_counter()
    doc = fitz.open(pdf_path)
    pages_with_text = 0
    diagram_pages = 0
    rendered_pages = 0
    warnings = 0
    tables = 0
    headings = 0
    total_chars = 0
    body_size = detect_body_size(doc) if detect_body_size else 10.0

    if render_dir:
        render_dir.mkdir(parents=True, exist_ok=True)

    for idx, page in enumerate(doc):
        raw_text = page.get_text("text") or ""
        compact = raw_text.strip()
        total_chars += len(compact)
        if compact:
            pages_with_text += 1
        warnings += len(re.findall(r"\bWARNING\b", raw_text, flags=re.I))
        tables += len(re.findall(r"\b(table|technical data|tightening specifications?)\b", raw_text, flags=re.I))

        if diagram_profile:
            has_diagram, _, _, _, _ = diagram_profile(page)
            if page_lines and is_heading:
                headings += sum(1 for line in page_lines(page) if is_heading(line, body_size))
        else:
            drawings = len(page.get_drawings())
            images = len(page.get_images(full=True))
            has_diagram = drawings > 20 or images > 0
            headings += len(re.findall(r"(?m)^[A-Z][^\n]{2,80}$", raw_text))

        if has_diagram:
            diagram_pages += 1
            if render_dir:
                pix = page.get_pixmap(dpi=render_dpi)
                pix.save(render_dir / f"page_{idx + 1:04d}.png")
                rendered_pages += 1

    page_count = len(doc)
    doc.close()
    elapsed = round(time.perf_counter() - started, 3)
    result = {
        "pipeline": "existing-pymupdf",
        "status": "ok",
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "diagram_pages": diagram_pages,
        "rendered_pages": rendered_pages,
        "text_chars": total_chars,
        "headings_detected": headings,
        "warnings_detected": warnings,
        "tables_detected": tables,
        "source_sha256": sha256_file(pdf_path),
        "page_anchored": True,
        "section_hierarchy": True,
        "elapsed_seconds": elapsed,
    }
    result.update(summarize_result(result))
    return result


def _docling_metrics(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        return {
            "pipeline": "docling",
            "status": "skipped",
            "reason": "Docling is not installed. Install with: pip install 'docling>=2,<3'",
            "source_sha256": sha256_file(pdf_path),
            "elapsed_seconds": 0.0,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()
    conversion = converter.convert(pdf_path)
    document = conversion.document
    markdown = document.export_to_markdown()
    (output_dir / "document.md").write_text(markdown, encoding="utf-8")
    try:
        doc_json = document.export_to_dict()
        (output_dir / "document.json").write_text(json.dumps(doc_json, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        doc_json = {}

    page_count = 0
    pages = getattr(document, "pages", None)
    if pages is not None:
        try:
            page_count = len(pages)
        except TypeError:
            page_count = len(list(pages))
    if not page_count:
        import fitz
        with fitz.open(pdf_path) as pdf:
            page_count = len(pdf)

    headings = len(re.findall(r"(?m)^#{1,6}\s+", markdown))
    warnings = len(re.findall(r"\bWARNING\b", markdown, flags=re.I))
    tables = len(re.findall(r"(?m)^\|.+\|\s*$", markdown))
    result = {
        "pipeline": "docling",
        "status": "ok",
        "page_count": page_count,
        "pages_with_text": page_count if markdown.strip() else 0,
        "diagram_pages": 0,
        "rendered_pages": 0,
        "text_chars": len(markdown),
        "headings_detected": headings,
        "warnings_detected": warnings,
        "tables_detected": tables,
        "source_sha256": sha256_file(pdf_path),
        "page_anchored": bool(doc_json),
        "section_hierarchy": headings > 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    result.update(summarize_result(result))
    return result


def run_benchmark(
    zip_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    include_docling: bool = True,
    render_baseline_diagrams: bool = True,
    include_external: bool = True,
    external_results_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    zip_path = Path(zip_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = discover_benchmark_manuals(zip_path)
    source_dir = output_dir / "sources"
    extracted = safe_extract_members(zip_path, [t.member_name for t in targets.values()], source_dir)

    external_manifest = None
    resolved_external_results = None
    if include_external:
        external_manifest = build_external_job_manifest(targets, extracted, output_dir)
        resolved_external_results = (
            Path(external_results_dir).resolve()
            if external_results_dir is not None
            else output_dir / "external-results"
        )

    report: dict[str, Any] = {
        "schema_version": 2,
        "source_zip": str(zip_path),
        "source_zip_sha256": sha256_file(zip_path),
        "external_job_manifest": str(external_manifest) if external_manifest else None,
        "targets": {},
    }

    for role, target in targets.items():
        pdf_path = extracted[target.member_name]
        role_dir = output_dir / role
        baseline_render_dir = role_dir / "existing-pymupdf" / "pages" if render_baseline_diagrams else None
        baseline = _baseline_metrics(pdf_path, baseline_render_dir)
        pipelines = [baseline]
        if include_docling:
            pipelines.append(_docling_metrics(pdf_path, role_dir / "docling"))
        if include_external:
            for pipeline in EXTERNAL_PIPELINES:
                pipelines.append(_load_external_result(pipeline, role, pdf_path, resolved_external_results))
        report["targets"][role] = {
            "manual": asdict(target),
            "file_size_bytes": pdf_path.stat().st_size,
            "source_sha256": sha256_file(pdf_path),
            "pipelines": pipelines,
        }

    (output_dir / "benchmark-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
