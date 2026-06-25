from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable

from .common import json_dump, now_iso, sha256_file
from .corpus import CorpusRecord
from .embeddings import OllamaEmbedder


def export_points(
    records: Iterable[CorpusRecord],
    root: Path,
    embedder: OllamaEmbedder,
    batch_size: int = 32,
) -> dict:
    qdrant_dir = root / "qdrant"
    qdrant_dir.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(root / "embedding_cache.sqlite")
    cache.execute(
        """CREATE TABLE IF NOT EXISTS embeddings (
        model TEXT NOT NULL, point_id TEXT NOT NULL, vector TEXT NOT NULL,
        PRIMARY KEY (model, point_id)
        )"""
    )
    temp_paths: dict[str, Path] = {}
    handles = {}
    counts: Counter[str] = Counter()
    rejected_path = root / "rejected_records.jsonl"
    rejected = rejected_path.open("w", encoding="utf-8")
    try:
        batch: list[CorpusRecord] = []

        def flush() -> None:
            if not batch:
                return
            vectors: list[list[float] | None] = [None] * len(batch)
            missing_indexes: list[int] = []
            for index, record in enumerate(batch):
                cached = cache.execute(
                    "SELECT vector FROM embeddings WHERE model = ? AND point_id = ?",
                    (embedder.model, record.point_id),
                ).fetchone()
                if cached:
                    vectors[index] = json.loads(cached[0])
                else:
                    missing_indexes.append(index)
            if missing_indexes:
                generated = embedder.embed([batch[index].text for index in missing_indexes])
                for index, vector in zip(missing_indexes, generated):
                    vectors[index] = vector
                    cache.execute(
                        "INSERT OR REPLACE INTO embeddings(model, point_id, vector) VALUES (?, ?, ?)",
                        (embedder.model, batch[index].point_id, json.dumps(vector)),
                    )
                cache.commit()
            if embedder.dimension is None and vectors and vectors[0]:
                embedder.dimension = len(vectors[0])
            for record, vector in zip(batch, vectors):
                if record.collection not in temp_paths:
                    temp_paths[record.collection] = (
                        qdrant_dir / f"{record.collection}.points.jsonl.tmp"
                    )
                if record.collection not in handles:
                    handles[record.collection] = temp_paths[record.collection].open(
                        "w", encoding="utf-8"
                    )
                handle = handles[record.collection]
                point = {
                    "id": record.point_id,
                    "vector": vector,
                    "payload": record.payload,
                }
                handle.write(json.dumps(point, ensure_ascii=False) + "\n")
                counts[record.collection] += 1
            batch.clear()

        for record in records:
            try:
                if not record.text:
                    raise ValueError("record text is empty")
                batch.append(record)
                if len(batch) >= batch_size:
                    flush()
                    print(f"\rEmbedded {sum(counts.values()):,} records", end="", flush=True)
            except Exception as exc:
                rejected.write(
                    json.dumps(
                        {"id": record.point_id, "error": str(exc)}, ensure_ascii=False
                    )
                    + "\n"
                )
        flush()
        print(f"\rEmbedded {sum(counts.values()):,} records")
    finally:
        rejected.close()
        for handle in handles.values():
            handle.close()
        cache.close()
    files = {}
    for collection, temp in temp_paths.items():
        final = temp.with_suffix("")
        os.replace(temp, final)
        files[collection] = {
            "file": final.name,
            "points": counts[collection],
            "sha256": sha256_file(final),
        }
    manifest = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "embedding_model": embedder.model,
        "vector_size": embedder.dimension,
        "distance": "Cosine",
        "collections": files,
        "rejected_file": rejected_path.name,
    }
    json_dump(root / "qdrant_manifest.json", manifest)
    return manifest
