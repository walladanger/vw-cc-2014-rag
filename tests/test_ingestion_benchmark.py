import json
import zipfile
from pathlib import Path

import pytest

from cc_workshop.ingestion_benchmark import (
    EXTERNAL_PIPELINES,
    build_external_job_manifest,
    discover_benchmark_manuals,
    normalize_external_result,
    safe_extract_members,
    summarize_result,
)


def _make_zip(tmp_path: Path) -> Path:
    zpath = tmp_path / "manuals.zip"
    names = [
        "No Watermark VW CC/Engine/D3E8012ED5C-Brake_System_reversed_trimmed_reversed.pdf",
        "No Watermark VW CC/Engine/D3E80480D47-4-Cylinder_Direct_Injection_(1_8L_and_2_0L_Engine__4V__Turbocharger__Chain_Drive)_reversed_trimmed_reversed.pdf",
        "No Watermark VW CC/Electrical/K0059040021-Wiring_Diagrams_and_Component_Locations_reversed_trimmed_reversed.pdf",
        "No Watermark VW CC/Body/unrelated.pdf",
    ]
    with zipfile.ZipFile(zpath, "w") as zf:
        for name in names:
            zf.writestr(name, b"%PDF-1.4\n%%EOF")
    return zpath


def test_discover_benchmark_manuals_finds_each_required_role(tmp_path):
    found = discover_benchmark_manuals(_make_zip(tmp_path))
    assert set(found) == {"brake", "engine", "wiring"}
    assert "Brake_System" in found["brake"].member_name
    assert "4-Cylinder_Direct_Injection" in found["engine"].member_name
    assert "Wiring_Diagrams" in found["wiring"].member_name


def test_discover_benchmark_manuals_raises_when_required_manual_missing(tmp_path):
    zpath = tmp_path / "missing.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("No Watermark VW CC/Engine/brake.pdf", b"%PDF-1.4\n%%EOF")
    with pytest.raises(ValueError, match="Missing benchmark manual"):
        discover_benchmark_manuals(zpath)


def test_safe_extract_members_rejects_zip_slip(tmp_path):
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../escape.pdf", b"bad")
    with pytest.raises(ValueError, match="unsafe zip member"):
        safe_extract_members(zpath, ["../escape.pdf"], tmp_path / "out")


def test_summarize_result_scores_provenance_and_visual_preservation():
    summary = summarize_result({
        "pipeline": "baseline",
        "status": "ok",
        "page_count": 100,
        "pages_with_text": 95,
        "diagram_pages": 40,
        "rendered_pages": 40,
        "source_sha256": "a" * 64,
        "page_anchored": True,
        "section_hierarchy": True,
        "warnings_detected": 12,
        "tables_detected": 4,
    })
    assert summary["provenance_ok"] is True
    assert summary["visual_preservation_ratio"] == 1.0
    assert summary["text_coverage_ratio"] == 0.95
    assert summary["quality_score"] > 0.8


def test_external_pipeline_registry_contains_selected_candidates():
    assert EXTERNAL_PIPELINES == (
        "ragflow",
        "nemo-retriever",
        "nvidia-rag-blueprint",
    )


def test_normalize_external_result_rejects_wrong_source_hash(tmp_path):
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"manual bytes")
    with pytest.raises(ValueError, match="source_sha256"):
        normalize_external_result(
            "ragflow",
            pdf,
            {
                "status": "ok",
                "source_sha256": "0" * 64,
                "page_count": 10,
                "pages_with_text": 10,
                "diagram_pages": 2,
                "rendered_pages": 2,
                "page_anchored": True,
                "section_hierarchy": True,
                "warnings_detected": 1,
                "tables_detected": 1,
            },
        )


def test_build_external_job_manifest_creates_jobs_for_every_role_and_pipeline(tmp_path):
    targets = discover_benchmark_manuals(_make_zip(tmp_path))
    extracted = safe_extract_members(
        _make_zip(tmp_path),
        [target.member_name for target in targets.values()],
        tmp_path / "sources",
    )
    manifest_path = build_external_job_manifest(targets, extracted, tmp_path / "benchmark")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = payload["jobs"]
    assert len(jobs) == 3 * len(EXTERNAL_PIPELINES)
    assert {job["pipeline"] for job in jobs} == set(EXTERNAL_PIPELINES)
    assert {job["role"] for job in jobs} == {"brake", "engine", "wiring"}
    assert all(job["source_sha256"] for job in jobs)
    assert all(job["result_path"].endswith(".json") for job in jobs)
