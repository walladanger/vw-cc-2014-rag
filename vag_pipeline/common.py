from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

NAMESPACE = uuid.UUID("8a933533-4583-45ad-b5be-a743d8e43996")
VIN_RE = re.compile(
    r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])", re.IGNORECASE
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(*parts: Any) -> str:
    material = "\x1f".join("" if p is None else str(p) for p in parts)
    return str(uuid.uuid5(NAMESPACE, material))


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc


def redact_vins(value: str) -> str:
    return VIN_RE.sub("[VIN REDACTED]", value)


def safe_vehicle_id(vin: str, salt: str) -> str:
    if not vin:
        return ""
    return "veh_" + hashlib.sha256(f"{salt}:{vin.upper()}".encode()).hexdigest()[:20]


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized_engine_codes(value: Any) -> list[str]:
    text = clean_text(value).upper()
    if not text:
        return []
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,4}\b", text)
    stop = {"ENGINE", "TSI", "TFSI", "TDI", "VAG", "VW", "AUDI", "NONE"}
    return sorted({item for item in candidates if item not in stop})
