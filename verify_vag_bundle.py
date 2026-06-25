#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from vag_pipeline.common import VIN_RE


def contains_vin(value) -> bool:
    if isinstance(value, str):
        return VIN_RE.search(value) is not None
    if isinstance(value, dict):
        return any(contains_vin(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_vin(item) for item in value)
    return False


def verify(root: Path) -> dict:
    manifest = json.loads(
        (root / "qdrant_manifest.json").read_text(encoding="utf-8")
    )
    result = {"collections": {}, "errors": []}
    total = 0
    for collection, info in manifest["collections"].items():
        path = root / "qdrant" / info["file"]
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as handle:
            for line_no, line in enumerate(handle, 1):
                digest.update(line)
                if not line.strip():
                    continue
                point = json.loads(line)
                if len(point.get("vector", [])) != manifest["vector_size"]:
                    result["errors"].append(
                        f"{collection}:{line_no}: invalid vector size"
                    )
                if contains_vin(point.get("payload", {})):
                    result["errors"].append(
                        f"{collection}:{line_no}: possible raw VIN"
                    )
                count += 1
        actual_hash = digest.hexdigest()
        if count != info["points"]:
            result["errors"].append(
                f"{collection}: expected {info['points']} points, found {count}"
            )
        if actual_hash != info["sha256"]:
            result["errors"].append(f"{collection}: checksum mismatch")
        result["collections"][collection] = {
            "points": count,
            "sha256": actual_hash,
        }
        total += count
    cached = 0
    cache_path = root / "embedding_cache.sqlite"
    if cache_path.exists():
        connection = sqlite3.connect(cache_path)
        try:
            cached = connection.execute(
                "SELECT count(*) FROM embeddings"
            ).fetchone()[0]
        finally:
            connection.close()
    result["total_points"] = total
    result["cached_vectors"] = cached
    result["ok"] = not result["errors"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a portable VAG data bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.bundle)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
