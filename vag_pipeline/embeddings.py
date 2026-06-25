from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Iterable


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.dimension: int | None = None

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [float(value / norm) for value in vector]

    def _post(self, route: str, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{route}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            payload = self._post("/api/embed", {"model": self.model, "input": texts})
            vectors = payload["embeddings"]
        except (urllib.error.HTTPError, KeyError):
            vectors = [
                self._post("/api/embeddings", {"model": self.model, "prompt": text})[
                    "embedding"
                ]
                for text in texts
            ]
        normalized = [self._normalize(list(vector)) for vector in vectors]
        if normalized:
            self.dimension = len(normalized[0])
        return normalized

    def embed_batches(
        self, texts: Iterable[str], batch_size: int
    ) -> Iterable[list[list[float]]]:
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= batch_size:
                yield self.embed(batch)
                batch = []
        if batch:
            yield self.embed(batch)
