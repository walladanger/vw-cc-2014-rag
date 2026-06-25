from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .common import (
    clean_text,
    json_dump,
    jsonl_rows,
    normalized_engine_codes,
    now_iso,
    sha256_file,
    stable_id,
)

COMMUNITY_TYPES = {"video", "guide", "community"}
COMMUNITY_PREFIXES = ("autodoc_", "humblemechanic_", "youtube_", "video_")


@dataclass
class CorpusRecord:
    collection: str
    point_id: str
    text: str
    payload: dict[str, Any]


def classify_chunk(chunk: dict[str, Any]) -> tuple[str, str]:
    source_type = clean_text(chunk.get("source_type")).lower()
    tier = clean_text(chunk.get("safety_tier")).lower()
    manual_id = clean_text(chunk.get("manual_id")).lower()
    if (
        tier == "community"
        or source_type in COMMUNITY_TYPES
        or manual_id.startswith(COMMUNITY_PREFIXES)
    ):
        return "vag_community_guides", "community"
    return "vag_manual_chunks", "authoritative"


def normalize_chunk(chunk: dict[str, Any], source_file: Path) -> CorpusRecord:
    collection, tier = classify_chunk(chunk)
    text = clean_text(chunk.get("text"))
    chunk_hash = clean_text(chunk.get("chunk_hash"))
    point_id = stable_id(
        collection,
        chunk.get("manual_id"),
        chunk.get("video_id"),
        chunk.get("chunk_id"),
        chunk.get("page_physical"),
        chunk.get("start_seconds"),
        chunk_hash,
        text,
    )
    engine_codes = normalized_engine_codes(chunk.get("engine"))
    payload = {
        "schema_version": 1,
        "source_tier": tier,
        "source_type": clean_text(chunk.get("source_type")) or (
            "guide" if tier == "community" else "manual"
        ),
        "chunk_id": clean_text(chunk.get("chunk_id")),
        "chunk_hash": chunk_hash,
        "manual_id": clean_text(chunk.get("manual_id")),
        "manual_title": clean_text(chunk.get("manual_title")),
        "pdf_filename": clean_text(chunk.get("pdf_filename")),
        "page_physical": chunk.get("page_physical"),
        "page_label": clean_text(chunk.get("page_label")),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "section_title": clean_text(chunk.get("section_title")),
        "system": clean_text(chunk.get("system")),
        "vehicle": clean_text(chunk.get("vehicle")),
        "engine": clean_text(chunk.get("engine")),
        "engine_codes": engine_codes,
        "model_year": chunk.get("model_year"),
        "has_diagram": bool(chunk.get("has_diagram")),
        "needs_ocr": bool(chunk.get("needs_ocr")),
        "page_image": clean_text(chunk.get("page_image")),
        "image_refs": chunk.get("image_refs") or [],
        "viewer_url": clean_text(chunk.get("viewer_url")),
        "source_hash": clean_text(chunk.get("source_hash")),
        "source_record": f"{source_file.parent.name}/{source_file.name}",
        "text": text,
        "char_count": len(text),
        "write_capability": "disabled",
    }
    return CorpusRecord(collection, point_id, text, payload)


def iter_corpus(out_dir: Path) -> Iterable[CorpusRecord]:
    for chunk_file in sorted(out_dir.rglob("chunks.jsonl")):
        for chunk in jsonl_rows(chunk_file):
            if clean_text(chunk.get("text")):
                yield normalize_chunk(chunk, chunk_file)


def build_source_ledger(out_dir: Path, destination: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for manifest_path in sorted(out_dir.rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        chunks_path = manifest_path.with_name("chunks.jsonl")
        sources.append(
            {
                "manual_id": clean_text(manifest.get("manual_id"))
                or manifest_path.parent.name,
                "manifest_path": str(manifest_path.relative_to(out_dir)),
                "manifest_hash": sha256_file(manifest_path),
                "chunks_path": (
                    str(chunks_path.relative_to(out_dir)) if chunks_path.exists() else ""
                ),
                "chunks_hash": sha256_file(chunks_path) if chunks_path.exists() else "",
                "source_filename": Path(
                    clean_text(manifest.get("source_path")) or "unknown"
                ).name,
                "source_hash": clean_text(manifest.get("source_hash")),
                "pipeline_version": clean_text(manifest.get("pipeline_version")),
            }
        )
    ledger = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "out_dir": str(out_dir),
        "source_count": len(sources),
        "sources": sources,
    }
    json_dump(destination, ledger)
    return ledger
