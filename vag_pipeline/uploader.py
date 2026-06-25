from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from .common import json_dump


def request_json(url: str, method: str, payload: dict | None, api_key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    request = urllib.request.Request(
        url,
        method=method,
        headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        return json.loads(body) if body else {}


def upload_bundle(
    bundle: Path,
    qdrant_url: str,
    api_key: str = "",
    batch_size: int = 128,
    recreate: bool = False,
) -> None:
    manifest = json.loads((bundle / "qdrant_manifest.json").read_text())
    state_path = bundle / "upload_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    base = qdrant_url.rstrip("/")
    for collection, info in manifest["collections"].items():
        if recreate:
            try:
                request_json(f"{base}/collections/{collection}", "DELETE", None, api_key)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        try:
            request_json(f"{base}/collections/{collection}", "GET", None, api_key)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            exc.close()
            request_json(
                f"{base}/collections/{collection}",
                "PUT",
                {
                    "vectors": {
                        "size": manifest["vector_size"],
                        "distance": manifest["distance"],
                    }
                },
                api_key,
            )
        completed = 0 if recreate else int(state.get(collection, 0))
        points: list[dict] = []
        line_no = 0
        file_path = bundle / "qdrant" / info["file"]
        with file_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if line_no <= completed:
                    continue
                points.append(json.loads(line))
                if len(points) >= batch_size:
                    request_json(
                        f"{base}/collections/{collection}/points?wait=true",
                        "PUT",
                        {"points": points},
                        api_key,
                    )
                    state[collection] = line_no
                    json_dump(state_path, state)
                    points = []
            if points:
                request_json(
                    f"{base}/collections/{collection}/points?wait=true",
                    "PUT",
                    {"points": points},
                    api_key,
                )
                state[collection] = line_no
                json_dump(state_path, state)
        print(f"{collection}: uploaded {state.get(collection, 0):,} points")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume-safe Qdrant bundle uploader")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    upload_bundle(args.bundle, args.url, args.api_key, args.batch_size, args.recreate)


if __name__ == "__main__":
    main()
