#!/usr/bin/env python3
"""
Video Retrieval Module (v1) — community-tier supplement to retrieve.py.

Provides hybrid BM25 + dense retrieval over video chunks from video_index.json
and the out/videos/{video_id}/chunks.jsonl files produced by ingest_video.py.

SAFETY CONTRACT
  - All results from this module are tagged  safety_tier = "community"
  - They must NEVER be passed to specverify.verify_answer()
  - Torque values found in video chunks trigger a conflict warning, not an answer
  - The generator must present video results as "see also", never as primary spec
  - If a video value conflicts with a manual value, SURFACE the conflict — never
    silently resolve it in the video's favour

Usage (standalone):
  python retrieve_video.py "DSG fluid change steps" -k 5
  python retrieve_video.py --selftest

Usage (from generation layer):
  from retrieve_video import VideoRetriever
  vr = VideoRetriever(out_dir="./out", embedder="ollama")
  results = vr.query("how do I change DSG fluid", k=5)
  for r in results:
      print(r["citation_label"], r["text"][:120])

Integration with retrieve.py:
  When the generation layer calls retrieve.py with --sources manuals,videos
  it should call BOTH retrievers and merge results, keeping tier labels intact.
  See assemble_context() below for the combined-context builder.
"""

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

# ──────────────────────────────────────────── optional deps

def _import_bm25():
    try:
        from rank_bm25 import BM25Okapi
        return BM25Okapi
    except ImportError:
        sys.exit("rank-bm25 not installed.  Run:  pip install rank-bm25")

def _embed_local(texts):
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(texts, show_progress_bar=False).tolist()
    except ImportError:
        return [[] for _ in texts]

def _embed_ollama(texts, base="http://localhost:11434"):
    import httpx
    out = []
    for t in texts:
        r = httpx.post(f"{base}/api/embeddings",
                       json={"model": "nomic-embed-text", "prompt": t}, timeout=30)
        out.append(r.json()["embedding"])
    return out

# ──────────────────────────────────────────── cosine

def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x*x for x in a))
    nb  = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb + 1e-9)

# ──────────────────────────────────────────── conflict re (same as ingest_video)

TORQUE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:nm|newton.?met(?:er|re)|foot.?pound|ft.?lb|"
    r"in.?lb|n\.m)\b"
    r"|(?:torque|tighten(?:ing)?|torqued?)\s+(?:to|at|is|of)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

VIDEO_INDEX_NAME = "video_index.json"

# ──────────────────────────────────────────── retriever class

class VideoRetriever:
    def __init__(
        self,
        out_dir: str = "./out",
        embedder: str = "local",
        ollama_base: str = "http://localhost:11434",
        cos_floor: float = 0.30,    # lower than manual floor — community content is noisier
        bm25_floor: float = 5.0,
        alpha: float = 0.6,         # weight for dense vs BM25 (0 = pure BM25, 1 = pure dense)
    ):
        self.out_dir     = out_dir
        self.embedder    = embedder
        self.ollama_base = ollama_base
        self.cos_floor   = cos_floor
        self.bm25_floor  = bm25_floor
        self.alpha       = alpha
        self._chunks: list[dict] = []
        self._bm25  = None
        self._loaded = False

    # ── index loading

    def _load(self):
        if self._loaded:
            return
        index_path = os.path.join(self.out_dir, VIDEO_INDEX_NAME)
        if not os.path.isfile(index_path):
            self._loaded = True
            return
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        for v in index.get("videos", []):
            cp = v.get("chunks_path") or os.path.join(
                self.out_dir, "videos", v["video_id"], "chunks.jsonl"
            )
            if not os.path.isfile(cp):
                continue
            with open(cp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._chunks.append(json.loads(line))
        if self._chunks:
            BM25Okapi = _import_bm25()
            self._bm25 = BM25Okapi([c["text"].lower().split() for c in self._chunks])
        self._loaded = True
        print(f"  [video retriever] loaded {len(self._chunks)} chunks from "
              f"{len(index.get('videos',[]))} videos", file=sys.stderr)

    # ── embed query

    def _embed_query(self, query: str) -> list[float]:
        if self.embedder == "ollama":
            try:
                return _embed_ollama([query], self.ollama_base)[0]
            except Exception as e:
                print(f"  [video retriever] Ollama embed failed ({e}), falling back to local",
                      file=sys.stderr)
        return _embed_local([query])[0]

    # ── query

    def query(self, query: str, k: int = 5) -> list[dict]:
        """
        Returns up to k video chunks ranked by hybrid BM25+dense score.
        Each result includes safety_tier, citation_label, and conflict_warning.
        Returns [] if nothing clears the gate.
        """
        self._load()
        if not self._chunks:
            return []

        tokens = query.lower().split()

        # BM25
        bm25_scores = self._bm25.get_scores(tokens) if self._bm25 else [0.0] * len(self._chunks)
        bm25_max = max(bm25_scores) if bm25_scores else 1.0

        # Dense
        qvec = self._embed_query(query)
        dense_scores = [
            _cosine(qvec, c.get("embedding", [])) for c in self._chunks
        ]
        dense_max = max(dense_scores) if dense_scores else 1.0

        # Hybrid
        results = []
        for i, chunk in enumerate(self._chunks):
            b_norm = bm25_scores[i] / (bm25_max + 1e-9)
            d_norm = dense_scores[i] / (dense_max + 1e-9)
            score  = self.alpha * d_norm + (1 - self.alpha) * b_norm

            # Gate: accept if dense cosine clears floor OR strong BM25 + lexical hit
            dense_ok = dense_scores[i] >= self.cos_floor
            bm25_ok  = (bm25_scores[i] >= self.bm25_floor and
                        any(t in chunk["text"].lower() for t in tokens if len(t) > 3))
            if not (dense_ok or bm25_ok):
                continue

            # Conflict warning — any torque value in a video chunk
            conflict_warning = None
            if chunk.get("has_spec_conflict"):
                values = [c.get("value") for c in chunk.get("spec_conflicts", [])
                          if c.get("type") == "torque_value" and c.get("value")]
                if values:
                    conflict_warning = (
                        f"⚠ Video mentions value(s) {', '.join(values)} Nm — "
                        f"verify against factory manual before using."
                    )

            ts = chunk.get("timestamp_label", "?:??")
            results.append({
                **chunk,
                "hybrid_score":     round(score, 4),
                "bm25_score":       round(float(bm25_scores[i]), 2),
                "dense_score":      round(float(dense_scores[i]), 4),
                "citation_label":   f"[Video: \"{chunk['title']}\", ~{ts}]",
                "citation_url":     _build_url(chunk.get("webpage_url"), chunk.get("timestamp_start")),
                "conflict_warning": conflict_warning,
                "safety_tier":      "community",   # always community — belt AND suspenders
            })

        results.sort(key=lambda r: r["hybrid_score"], reverse=True)
        return results[:k]

    # ── selftest

    def selftest(self):
        """
        Sanity-check the video index.
        Prints chunk counts, sample queries, and conflict summary.
        Does NOT check safety gates (those are in the generation layer).
        """
        self._load()
        print(f"\n{'='*60}")
        print(f"VIDEO RETRIEVAL SELFTEST")
        print(f"{'='*60}")
        print(f"Total video chunks loaded: {len(self._chunks)}")

        if not self._chunks:
            print("  No video chunks found — run ingest_video.py first.")
            return

        # System breakdown
        from collections import Counter
        systems = Counter(c.get("system", "unknown") for c in self._chunks)
        print("\nChunks by system:")
        for sys_name, count in systems.most_common():
            print(f"  {sys_name:<30} {count:>5}")

        # Conflict summary
        conflicts = sum(1 for c in self._chunks if c.get("has_spec_conflict"))
        print(f"\nChunks with spec conflicts: {conflicts}/{len(self._chunks)}")

        # Safety tier check
        non_community = [c for c in self._chunks if c.get("safety_tier") != "community"]
        if non_community:
            print(f"\n⛔ SAFETY ERROR: {len(non_community)} chunks are NOT tagged community!")
        else:
            print("\n✓ All chunks tagged safety_tier=community")

        # Sample query
        print("\nSample query: 'DSG fluid change'")
        results = self.query("DSG fluid change", k=3)
        if results:
            for r in results:
                print(f"  score={r['hybrid_score']}  {r['citation_label']}")
                print(f"    {r['text'][:100]}…")
        else:
            print("  No results (expected if DSG video not yet ingested)")

        print(f"\n{'='*60}")

# ──────────────────────────────────────────── URL builder

def _build_url(webpage_url: str | None, timestamp: float | None) -> str | None:
    """Build a timestamped YouTube URL like https://youtu.be/xyz?t=254"""
    if not webpage_url:
        return None
    if timestamp and ("youtube.com" in webpage_url or "youtu.be" in webpage_url):
        return f"{webpage_url}&t={int(timestamp)}"
    return webpage_url

# ──────────────────────────────────────────── context assembler

def assemble_context(
    manual_results: list[dict],
    video_results: list[dict],
    max_chars: int = 6000,
) -> tuple[str, list[str], list[str]]:
    """
    Combine manual + video results into a generation context string.

    Returns:
        context_text    — the full context to pass to the LLM
        manual_cids     — chunk_ids from manuals (safe to pass to specverify)
        conflict_notes  — list of conflict warning strings to append to the answer

    Safety rules baked in:
      - Manual chunks appear first and are labelled [MANUAL — CANONICAL]
      - Video chunks appear after, labelled [VIDEO — COMMUNITY, verify specs]
      - Any video conflict warning is collected into conflict_notes
      - The LLM prompt must instruct: numbers from VIDEO sections require
        manual cross-check before use
    """
    parts = []
    manual_cids = []
    conflict_notes = []
    chars = 0

    if manual_results:
        parts.append("### FACTORY MANUAL SOURCES [CANONICAL — specverify enforced]")
        for r in manual_results:
            cid = r.get("chunk_id", "")
            manual_cids.append(cid)
            label = (
                f"[Manual: {r.get('manual_id','?')}, "
                f"Page {r.get('physical_page','?')}]"
            )
            block = f"\n{label}\n{r.get('text','')}\n"
            if chars + len(block) > max_chars * 0.7:
                break
            parts.append(block)
            chars += len(block)

    if video_results:
        parts.append("\n### COMMUNITY VIDEO SOURCES [verify specs against manual before use]")
        for r in video_results:
            label = r.get("citation_label", "")
            url   = r.get("citation_url", "")
            block = f"\n{label}"
            if url:
                block += f"  ({url})"
            block += f"\n{r.get('text','')}\n"
            if chars + len(block) > max_chars:
                break
            parts.append(block)
            chars += len(block)
            if r.get("conflict_warning"):
                conflict_notes.append(r["conflict_warning"])

    return "\n".join(parts), manual_cids, conflict_notes

# ──────────────────────────────────────────── CLI

def main():
    parser = argparse.ArgumentParser(description="Query the video retrieval index")
    parser.add_argument("query", nargs="?", help="Query string")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--out",         default="./out")
    parser.add_argument("--embedder",    default="local", choices=["local", "ollama"])
    parser.add_argument("--ollama-base", default="http://localhost:11434")
    parser.add_argument("--cos-floor",   type=float, default=0.30)
    parser.add_argument("--selftest",    action="store_true")
    args = parser.parse_args()

    vr = VideoRetriever(
        out_dir     = args.out,
        embedder    = args.embedder,
        ollama_base = args.ollama_base,
        cos_floor   = args.cos_floor,
    )

    if args.selftest:
        vr.selftest()
        return

    if not args.query:
        parser.print_help()
        return

    results = vr.query(args.query, k=args.k)
    if not results:
        print("REFUSE — no video chunks cleared the gate for this query.")
        return

    print(f"\n{'='*60}")
    print(f"VIDEO RESULTS for: '{args.query}'")
    print(f"{'='*60}")
    for i, r in enumerate(results, 1):
        print(f"\n#{i}  score={r['hybrid_score']}  {r['citation_label']}")
        if r.get("citation_url"):
            print(f"     {r['citation_url']}")
        print(f"     tier={r['safety_tier']}  system={r.get('system','?')}")
        if r.get("conflict_warning"):
            print(f"     {r['conflict_warning']}")
        print(f"\n  {r['text'][:300]}…")

    print(f"\n{'='*60}")
    print("⚠  All results above are community tier.")
    print("   Safety-critical specs must be verified against the factory manual.")


if __name__ == "__main__":
    main()
