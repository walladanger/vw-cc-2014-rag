#!/usr/bin/env python3
"""
One-time migration: load all chunks.jsonl + cached embeddings → ChromaDB.

Usage:
    python build_vectordb.py              # build everything
    python build_vectordb.py --reset      # drop and rebuild from scratch
    python build_vectordb.py --status     # show collection stats only

Output: out/chroma_db/   (persistent, never re-embedded unless --reset)
"""
import argparse
import glob
import hashlib
import json
import os
import struct
import sys

CHROMA_DIR = os.path.join("out", "chroma_db")
COLLECTION  = "vw_rag"
DIM         = 384  # all-MiniLM-L6-v2


def load_manual_embeddings(out_dir: str, chunks: list[dict]) -> list[list[float]] | None:
    """Load pre-computed MiniLM vectors from the .embcache binary file.
    Returns list aligned to chunks, or None if cache is missing/mismatched."""
    cache_dir = os.path.join(out_dir, ".embcache")
    if not os.path.isdir(cache_dir):
        return None
    # Replicate the cache key from retrieve.py
    h = hashlib.sha256()
    h.update("local:all-MiniLM-L6-v2".encode())
    for c in chunks:
        h.update(c["chunk_hash"].encode())
    path = os.path.join(cache_dir, h.hexdigest()[:16] + ".vec")
    if not os.path.isfile(path):
        print(f"  .embcache miss ({h.hexdigest()[:16]}.vec not found) — will re-embed")
        return None
    with open(path, "rb") as f:
        dim = struct.unpack("<I", f.read(4))[0]
        n   = struct.unpack("<I", f.read(4))[0]
        buf = f.read(dim * n * 4)
    if len(buf) != dim * n * 4:
        print("  .embcache truncated — will re-embed")
        return None
    flat = struct.unpack(f"<{dim*n}f", buf)
    vecs = [list(flat[i * dim:(i + 1) * dim]) for i in range(n)]
    print(f"  Loaded {n} vectors from .embcache (dim={dim})")
    return vecs


def embed_with_minilm(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    print("  Loading all-MiniLM-L6-v2 …")
    m = SentenceTransformer("all-MiniLM-L6-v2")
    B = 64
    out = []
    for i in range(0, len(texts), B):
        batch = texts[i:i + B]
        vecs = m.encode(batch, normalize_embeddings=True)
        out.extend([list(map(float, v)) for v in vecs])
        print(f"\r  Embedding {min(i+B, len(texts))}/{len(texts)}", end="", flush=True)
    print()
    return out


def build(out_dir: str, reset: bool):
    import chromadb

    # ── 1. load all chunks ──────────────────────────────────────────────────
    print("Loading chunks …")
    manual_chunks = []
    video_chunks  = []

    for path in sorted(glob.glob(os.path.join(out_dir, "*", "chunks.jsonl"))):
        # skip video sub-paths (they appear under out/videos/*/chunks.jsonl)
        if os.sep + "videos" + os.sep in path or "/videos/" in path:
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                manual_chunks.append(json.loads(line))

    for path in sorted(glob.glob(os.path.join(out_dir, "videos", "*", "chunks.jsonl"))):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                video_chunks.append(json.loads(line))

    print(f"  {len(manual_chunks)} manual chunks, {len(video_chunks)} video chunks")

    # ── 2. get embeddings ───────────────────────────────────────────────────
    print("Loading manual embeddings …")
    manual_vecs = load_manual_embeddings(out_dir, manual_chunks)
    if manual_vecs is None or len(manual_vecs) != len(manual_chunks):
        print("  Re-embedding manual chunks with all-MiniLM-L6-v2 …")
        manual_vecs = embed_with_minilm([c["text"] for c in manual_chunks])

    print("Loading video embeddings …")
    video_vecs = []
    missing_video = []
    for i, c in enumerate(video_chunks):
        emb = c.get("embedding")
        if emb and len(emb) == DIM:
            video_vecs.append(emb)
        else:
            missing_video.append(i)
            video_vecs.append(None)
    if missing_video:
        print(f"  Re-embedding {len(missing_video)} video chunks missing embeddings …")
        texts = [video_chunks[i]["text"] for i in missing_video]
        new_vecs = embed_with_minilm(texts)
        for j, i in enumerate(missing_video):
            video_vecs[i] = new_vecs[j]

    # ── 3. open ChromaDB ────────────────────────────────────────────────────
    print(f"Opening ChromaDB at {CHROMA_DIR} …")
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    if reset and COLLECTION in [c.name for c in client.list_collections()]:
        print("  Dropping existing collection …")
        client.delete_collection(COLLECTION)

    col = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    existing = col.count()
    print(f"  Collection '{COLLECTION}': {existing} docs already stored")

    # ── 4. upsert manual chunks ─────────────────────────────────────────────
    print("Upserting manual chunks …")
    BATCH = 500
    manual_ids = [c["chunk_id"] for c in manual_chunks]
    existing_ids = set()
    if not reset and existing > 0:
        # fetch existing ids to skip already-stored ones
        got = col.get(ids=manual_ids, include=[])
        existing_ids = set(got["ids"])

    to_add_idx = [i for i, c in enumerate(manual_chunks) if c["chunk_id"] not in existing_ids]
    print(f"  {len(to_add_idx)} manual chunks to upsert (skipping {len(existing_ids)} already stored)")

    for start in range(0, len(to_add_idx), BATCH):
        batch_idx = to_add_idx[start:start + BATCH]
        col.upsert(
            ids         = [manual_chunks[i]["chunk_id"] for i in batch_idx],
            embeddings  = [manual_vecs[i] for i in batch_idx],
            documents   = [manual_chunks[i]["text"] for i in batch_idx],
            metadatas   = [{
                "source_type":   "manual",
                "manual_id":     c.get("manual_id", ""),
                "manual_title":  c.get("manual_title", ""),
                "system":        c.get("system", ""),
                "vehicle":       c.get("vehicle", ""),
                "page_physical": c.get("page_physical", 0),
                "page_label":    str(c.get("page_label") or ""),
                "section_title": c.get("section_title") or "",
                "has_diagram":   bool(c.get("has_diagram")),
                "viewer_url":    c.get("viewer_url", ""),
            } for c in [manual_chunks[i] for i in batch_idx]],
        )
        done = min(start + BATCH, len(to_add_idx))
        print(f"\r  {done}/{len(to_add_idx)}", end="", flush=True)
    print()

    # ── 5. upsert video chunks ──────────────────────────────────────────────
    print("Upserting video chunks …")
    video_ids = [c["chunk_id"] for c in video_chunks]
    vid_existing = set()
    if not reset and existing > 0:
        got = col.get(ids=video_ids, include=[])
        vid_existing = set(got["ids"])

    to_add_vid = [i for i, c in enumerate(video_chunks) if c["chunk_id"] not in vid_existing]
    print(f"  {len(to_add_vid)} video chunks to upsert")

    for start in range(0, len(to_add_vid), BATCH):
        batch_idx = to_add_vid[start:start + BATCH]
        col.upsert(
            ids        = [video_chunks[i]["chunk_id"] for i in batch_idx],
            embeddings = [video_vecs[i] for i in batch_idx],
            documents  = [video_chunks[i]["text"] for i in batch_idx],
            metadatas  = [{
                "source_type":  "video",
                "video_id":     c.get("video_id", ""),
                "title":        c.get("title", ""),
                "channel":      c.get("channel", ""),
                "system":       c.get("system", ""),
                "vehicle":      c.get("vehicle", ""),
                "frame_path":   c.get("frame_path", ""),
                "frame_timestamp": float(c.get("frame_timestamp") or 0),
                "timestamp_start": float(c.get("timestamp_start") or 0),
                "webpage_url":  c.get("webpage_url", ""),
            } for c in [video_chunks[i] for i in batch_idx]],
        )
        done = min(start + BATCH, len(to_add_vid))
        print(f"\r  {done}/{len(to_add_vid)}", end="", flush=True)
    print()

    total = col.count()
    print(f"\nDone. ChromaDB collection '{COLLECTION}' has {total} documents.")


def status():
    import chromadb
    if not os.path.isdir(CHROMA_DIR):
        print("ChromaDB not built yet. Run: python build_vectordb.py")
        return
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    cols = client.list_collections()
    for c in cols:
        col = client.get_collection(c.name)
        print(f"Collection '{c.name}': {col.count()} documents")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build ChromaDB vector store from chunks.jsonl")
    p.add_argument("--reset",  action="store_true", help="Drop and rebuild from scratch")
    p.add_argument("--status", action="store_true", help="Show collection stats")
    p.add_argument("--out",    default="out",        help="Library output directory")
    args = p.parse_args()

    if args.status:
        status()
    else:
        build(args.out, reset=args.reset)
