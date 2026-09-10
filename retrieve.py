#!/usr/bin/env python3
"""
Manual-backed retrieval + grounding gate (v1).

This is the load-bearing piece of the spec: it enforces
    "No manual citation means no technical answer."

Pipeline:
  1. Load every chunks.jsonl in the library into one index.
  2. Score a query with HYBRID retrieval:
       - BM25 lexical   (great for torque values, part numbers, engine codes)
       - dense cosine   (great for natural-language questions)
     scores are min-max normalised per-query and blended.
  3. GROUNDING GATE: decide ACCEPT vs REFUSE *before* any answer is generated.
       - dense cosine of the best hit is the semantic-relevance signal
       - a strong BM25 hit can also clear the gate (exact spec lookups)
       - if neither clears the floor -> refuse with the spec's exact wording.
  4. On ACCEPT, assemble a citation-bearing evidence context for the generator
     and expose a structural citation check the generator's output must pass.

Embedding backend is pluggable:
  --embedder local   sentence-transformers all-MiniLM-L6-v2  (offline demo)
  --embedder ollama  POST /api/embeddings nomic-embed-text   (your TrueNAS box)
The retrieval and gate logic are identical across backends.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import struct
import sys
import urllib.request

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# ── vehicle applicability ──────────────────────────────────────────────────────
# Every chunk carries the "vehicle"/"engine" stamped at ingest time
# (ingest_manual.py --vehicle / --engine). Retrieval must not hand back another
# car's specs, because specverify proves only that a number was copied from a
# cited chunk -- not that the chunk applies to the car being asked about. An
# index holding more than one vehicle can therefore return a correct spec for
# the WRONG car and still report it VERIFIED, which is worse than refusing.
#
# Applicability is a hierarchy rather than a boolean: a generic multi-model
# reference (the shared VW DTC lists) still applies to this car, while another
# model's specifics do not. Plain substring matching cannot express that -- it
# either drops the generic references or admits everything.
_MARQUES = {
    "vw": "vw", "volkswagen": "vw",
    "audi": "audi",
    "skoda": "skoda", "škoda": "skoda",
    "seat": "seat",
}
_GENERIC_MARKERS = {"multi", "model", "models", "multimodel", "all", "generic", "various"}


def _norm_applicability(value):
    """'2014 VW CC 2.0T TSI' -> '2014 vw cc 2 0t tsi'. Both sides normalise the
    same way, so punctuation and casing differences cannot cause a false miss."""
    return " ".join(TOKEN_RE.findall(str(value or "").lower()))


def _marque_of(tokens):
    for t in tokens:
        if t in _MARQUES:
            return _MARQUES[t]
    return None


def _is_generic(tokens):
    """True when the value names nothing beyond a marque and/or a multi-model
    marker -- e.g. 'VW', 'VW (multi-model)', 'multi'."""
    return not [t for t in tokens if t not in _MARQUES and t not in _GENERIC_MARKERS]


def _engine_agrees(chunk, profile):
    want = _norm_applicability(profile.get("engine")).split()
    got = _norm_applicability(chunk.get("engine")).split()
    if not want or not got:
        return True
    if _is_generic(got) or _is_generic(want):
        return True
    return got == want


def applies_to_vehicle(chunk, profile):
    """Does this chunk apply to the active vehicle? Rules, in order:

    1. No active profile -> applies. Filtering is opt-in.
    2. Nothing stamped on the chunk -> applies. Indexes built before
       applicability was enforced must keep working, so this fails OPEN.
    3. Generic reference -> applies unless it names a different marque, so the
       shared DTC lists stay retrievable for any VW.
    4. Otherwise the chunk names a specific vehicle, and applies only when that
       matches the profile. Engine is then checked the same way, excluding only
       when both sides name a specific engine and those disagree.
    """
    if not profile:
        return True
    want_v = _norm_applicability(profile.get("vehicle"))
    if not want_v:
        return True
    got_v = _norm_applicability(chunk.get("vehicle"))
    if not got_v:
        return True

    want_tokens, got_tokens = want_v.split(), got_v.split()
    if _is_generic(got_tokens):
        want_marque, got_marque = _marque_of(want_tokens), _marque_of(got_tokens)
        return not (got_marque and want_marque and got_marque != want_marque)

    if got_v != want_v:
        return False
    return _engine_agrees(chunk, profile)


# VW tables of contents use spaced dot leaders: ". . . . ." as well as "....".
_TOC_RE = re.compile(r"\.(\s?\.){3,}")
REFUSAL = "I do not have enough manual-backed information to answer that safely."


def tokenize(text):
    return [t.lower() for t in TOKEN_RE.findall(text)]


# ----------------------------------------------------------------- embedders


class LocalEmbedder:
    """sentence-transformers all-MiniLM-L6-v2 (384d). Offline demo backend."""

    name = "local:all-MiniLM-L6-v2"
    dim = 384

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self._m = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)

    def encode(self, texts, **_):
        return [list(map(float, v)) for v in self._m.encode(texts, normalize_embeddings=True)]

    def encode_query(self, text):
        return self.encode([text])[0]


class OllamaEmbedder:
    """Production backend: your local Ollama. nomic-embed-text is 768d."""

    def __init__(self, model="nomic-embed-text", host="http://localhost:11434"):
        self.name = f"ollama:{model}"
        self.model = model
        self.host = host.rstrip("/")
        self.dim = None

    def encode(self, texts, **_):
        out = []
        for t in texts:
            req = urllib.request.Request(
                f"{self.host}/api/embeddings",
                data=json.dumps({"model": self.model, "prompt": t}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                v = json.loads(r.read())["embedding"]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    def encode_query(self, text):
        return self.encode([text])[0]


class GeminiEmbedder:
    """Google Gemini text-embedding-004 (768d). Asymmetric: document vs query task types.
    Requires GOOGLE_API_KEY env var and: pip install google-genai"""

    dim = 3072
    _BATCH = 100  # texts per request (API limit)

    def __init__(self, api_key=None, model="gemini-embedding-2"):
        try:
            from google import genai
            from google.genai import types as gtypes
        except ImportError:
            sys.exit("GeminiEmbedder requires: pip install google-genai")
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            sys.exit("GeminiEmbedder requires GOOGLE_API_KEY env var")
        self._client = genai.Client(api_key=key)
        self._types  = gtypes
        self._model  = model
        self.name    = f"gemini:{model}"

    def encode(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        out = []
        for i in range(0, len(texts), self._BATCH):
            batch = texts[i:i + self._BATCH]
            resp = self._client.models.embed_content(
                model=self._model,
                contents=batch,
                config=self._types.EmbedContentConfig(task_type=task_type),
            )
            for emb in resp.embeddings:
                v = emb.values
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                out.append([x / n for x in v])
        return out

    def encode_query(self, text):
        return self.encode([text], task_type="RETRIEVAL_QUERY")[0]


def make_embedder(kind):
    if kind == "ollama":
        return OllamaEmbedder(
            model=os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            host=os.environ.get("OLLAMA_BASE", "http://localhost:11434"),
        )
    if kind == "gemini":
        return GeminiEmbedder()
    return LocalEmbedder()


# ----------------------------------------------------------------- index


class Library:
    def __init__(self, out_dir, embedder, chunks=None):
        self.embedder = embedder
        if chunks is not None:
            self.chunks = chunks
        else:
            self.chunks = []
            for path in sorted(glob.glob(os.path.join(out_dir, "*", "chunks.jsonl"))):
                for line in open(path, encoding="utf-8"):
                    line = line.strip()
                    if line:
                        self.chunks.append(json.loads(line))
            if not self.chunks:
                sys.exit(f"no chunks found under {out_dir}")
        self._bm25 = BM25Okapi([tokenize(c["text"] + " " + (c.get("section_title") or "")) for c in self.chunks])
        self._vectors = None  # lazy; loaded/built on first dense query
        self._out_dir = out_dir

    # -- dense vectors with on-disk cache keyed by embedder + corpus hash
    def _cache_path(self):
        h = hashlib.sha256()
        h.update(self.embedder.name.encode())
        for c in self.chunks:
            h.update(c["chunk_hash"].encode())
        os.makedirs(os.path.join(self._out_dir, ".embcache"), exist_ok=True)
        return os.path.join(self._out_dir, ".embcache", h.hexdigest()[:16] + ".vec")

    def _ensure_vectors(self):
        if self._vectors is not None:
            return
        cp = self._cache_path()
        if os.path.exists(cp):
            with open(cp, "rb") as f:
                dim = struct.unpack("<I", f.read(4))[0]
                n = struct.unpack("<I", f.read(4))[0]
                buf = f.read(dim * n * 4)
            flat = struct.unpack(f"<{dim*n}f", buf)
            self._vectors = [list(flat[i * dim:(i + 1) * dim]) for i in range(n)]
            return
        vecs = []
        B = 64
        texts = [c["text"] for c in self.chunks]
        for i in range(0, len(texts), B):
            vecs.extend(self.embedder.encode(texts[i:i + B]))
            print(f"\r  embedding {min(i+B,len(texts))}/{len(texts)}", end="", file=sys.stderr)
        print("", file=sys.stderr)
        self._vectors = vecs
        dim = len(vecs[0])
        with open(cp, "wb") as f:
            f.write(struct.pack("<I", dim))
            f.write(struct.pack("<I", len(vecs)))
            for v in vecs:
                f.write(struct.pack(f"<{dim}f", *v))

    # -- retrieval
    def _passes_filter(self, c, manual_id, system, vehicle_kw, profile=None):
        if manual_id and c.get("manual_id") != manual_id:
            return False
        if system and (c.get("system") or "").lower() != system.lower():
            return False
        if vehicle_kw and vehicle_kw.lower() not in (c.get("vehicle") or "").lower():
            return False
        if profile and not applies_to_vehicle(c, profile):
            return False
        return True

    def _boost(self, query, c, blended):
        """Rerank signal on top of the hybrid score:
          + section_title shares content words with the query (procedure titles
            are highly indicative of what a page is actually about)
          + an exact query phrase (>=2 words) appears in the text
          - the chunk looks like a table-of-contents / index entry (dot leaders,
            'Contents', 'Rep. Gr.' headers) -- navigation, not an answer."""
        qtoks = set(_content_tokens(query))
        if not qtoks:
            return blended
        sec = (c.get("section_title") or "").lower()
        text = c["text"].lower()
        bonus = 0.0
        sec_overlap = sum(t in sec for t in qtoks) / len(qtoks)
        bonus += 0.18 * sec_overlap
        ql = [t for t in tokenize(query) if t not in _STOP]
        for i in range(len(ql) - 1):
            if f"{ql[i]} {ql[i+1]}" in text:
                bonus += 0.10
                break
        if (_TOC_RE.search(c["text"]) or sec.startswith("contents")
                or "rep. gr." in sec):
            bonus -= 0.30
        return blended + bonus

    def retrieve(self, query, k=5, alpha=0.5, manual_id=None, system=None,
                 vehicle_kw=None, boost=False, profile=None):
        idx = [i for i, c in enumerate(self.chunks)
               if self._passes_filter(self.chunks[i], manual_id, system, vehicle_kw,
                                      profile)]
        if not idx:
            return []
        # lexical
        bm = self._bm25.get_scores(tokenize(query))
        bm_sub = [bm[i] for i in idx]
        bm_raw = {i: bm[i] for i in idx}
        # dense
        self._ensure_vectors()
        qv = self.embedder.encode_query(query)
        cos = {i: sum(a * b for a, b in zip(qv, self._vectors[i])) for i in idx}

        def norm(d):
            vals = list(d.values())
            lo, hi = min(vals), max(vals)
            rng = (hi - lo) or 1.0
            return {i: (v - lo) / rng for i, v in d.items()}

        bm_n = norm(bm_raw)
        cos_n = norm(cos)
        scored = []
        for i in idx:
            blended = alpha * cos_n[i] + (1 - alpha) * bm_n[i]
            if boost:
                blended = self._boost(query, self.chunks[i], blended)
            scored.append((i, blended, cos[i], bm_raw[i]))
        scored.sort(key=lambda x: x[1], reverse=True)
        out = []
        for i, blended, cosine, bmraw in scored[:k]:
            c = self.chunks[i]
            out.append({
                "chunk_id": c["chunk_id"], "manual_id": c["manual_id"],
                "manual_title": c["manual_title"], "page_physical": c["page_physical"],
                "page_label": c.get("page_label"), "section_title": c.get("section_title"),
                "system": c.get("system"), "vehicle": c.get("vehicle"),
                "has_diagram": c.get("has_diagram"), "page_image": c.get("page_image"),
                "viewer_url": c["viewer_url"], "text": c["text"],
                "score": round(blended, 4), "cosine": round(cosine, 4), "bm25": round(bmraw, 3),
            })
        return out


# ----------------------------------------------------------------- dual retrieval


def _rrf_merge(res_a, res_b, k=60, top_n=7):
    """Reciprocal Rank Fusion of two result lists. Returns at most top_n results.
    cosine field is set to max(cosine_a, cosine_b) so the gate can use either."""
    scores = {}
    data = {}
    for rank, r in enumerate(res_a):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        data[cid] = r.copy()
        data[cid]["cosine_local"] = r["cosine"]
    for rank, r in enumerate(res_b):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        if cid in data:
            data[cid]["cosine_gemini"] = r["cosine"]
            data[cid]["cosine"] = max(data[cid]["cosine"], r["cosine"])
        else:
            data[cid] = r.copy()
            data[cid]["cosine_gemini"] = r["cosine"]
            data[cid]["cosine_local"] = 0.0
    ordered = sorted(scores, key=lambda c: scores[c], reverse=True)[:top_n]
    out = []
    for cid in ordered:
        r = data[cid]
        r["rrf_score"] = round(scores[cid], 5)
        out.append(r)
    return out


class DualLibrary:
    """Hybrid retrieval using two dense embedders merged via Reciprocal Rank Fusion.
    Chunks are loaded once from disk and shared between both inner Libraries."""

    def __init__(self, out_dir, embedder_local, embedder_gemini):
        # Load chunks once
        chunks = []
        for path in sorted(glob.glob(os.path.join(out_dir, "*", "chunks.jsonl"))):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))
        if not chunks:
            sys.exit(f"no chunks found under {out_dir}")
        self.chunks = chunks
        self._lib_local  = Library(out_dir, embedder_local,  chunks=chunks)
        self._lib_gemini = Library(out_dir, embedder_gemini, chunks=chunks)
        self.embedder    = embedder_local   # primary (status display)
        self.embedder_b  = embedder_gemini

    def retrieve(self, query, k=5, alpha=0.5, manual_id=None, system=None,
                 vehicle_kw=None, boost=False, profile=None):
        res_local  = self._lib_local.retrieve(
            query, k=k * 2, alpha=alpha, manual_id=manual_id,
            system=system, vehicle_kw=vehicle_kw, boost=boost, profile=profile)
        res_gemini = self._lib_gemini.retrieve(
            query, k=k * 2, alpha=alpha, manual_id=manual_id,
            system=system, vehicle_kw=vehicle_kw, boost=boost, profile=profile)
        return _rrf_merge(res_local, res_gemini, top_n=k)


# ----------------------------------------------------------------- ChromaDB-backed library


class ChromaLibrary:
    """Hybrid BM25 + ANN retrieval backed by a persistent ChromaDB vector store.
    Vectors live on disk; only chunk text and metadata are held in memory.
    Drop-in replacement for Library — same retrieve() signature and return format."""

    _CHROMA_DIR = "chroma_db"
    _COLLECTION = "vw_rag"
    _CANDIDATE_K = 200  # top-k from each source before blending

    def __init__(self, out_dir: str, embedder):
        import chromadb as _chromadb

        self.embedder = embedder
        self._out_dir = out_dir

        # Load manual chunks only (videos handled by VideoRetriever)
        self.chunks: list[dict] = []
        for path in sorted(glob.glob(os.path.join(out_dir, "*", "chunks.jsonl"))):
            if (os.sep + "videos" + os.sep) in path or "/videos/" in path:
                continue
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    self.chunks.append(json.loads(line))
        if not self.chunks:
            sys.exit(f"ChromaLibrary: no manual chunks under {out_dir}")

        # Fast chunk_id → chunk lookup
        self._by_id: dict[str, dict] = {c["chunk_id"]: c for c in self.chunks}
        self._ids: list[str] = [c["chunk_id"] for c in self.chunks]

        # BM25 (text-only, fast to build)
        self._bm25 = BM25Okapi([
            tokenize(c["text"] + " " + (c.get("section_title") or ""))
            for c in self.chunks
        ])

        # ChromaDB persistent client
        chroma_path = os.path.join(out_dir, self._CHROMA_DIR)
        if not os.path.isdir(chroma_path):
            sys.exit(f"ChromaDB not found at {chroma_path}. Run: python build_vectordb.py")
        client = _chromadb.PersistentClient(path=chroma_path)
        self._col = client.get_collection(self._COLLECTION)

    # ── filters / boosting (identical to Library) ──────────────────────────

    def _passes_filter(self, c, manual_id, system, vehicle_kw, profile=None):
        if manual_id and c.get("manual_id") != manual_id:
            return False
        if system and (c.get("system") or "").lower() != system.lower():
            return False
        if vehicle_kw and vehicle_kw.lower() not in (c.get("vehicle") or "").lower():
            return False
        return applies_to_vehicle(c, profile)

    def _boost(self, query, c, blended):
        qtoks = set(_content_tokens(query))
        if not qtoks:
            return blended
        sec  = (c.get("section_title") or "").lower()
        text = c["text"].lower()
        bonus = 0.0
        sec_overlap = sum(t in sec for t in qtoks) / len(qtoks)
        bonus += 0.18 * sec_overlap
        ql = [t for t in tokenize(query) if t not in _STOP]
        for i in range(len(ql) - 1):
            if f"{ql[i]} {ql[i+1]}" in text:
                bonus += 0.10
                break
        if _TOC_RE.search(c["text"]) or sec.startswith("contents") or "rep. gr." in sec:
            bonus -= 0.30
        return blended + bonus

    # ── main retrieval ──────────────────────────────────────────────────────

    def retrieve(self, query, k=5, alpha=0.5, manual_id=None, system=None,
                 vehicle_kw=None, boost=False, profile=None):
        # 1. Dense: top-k from ChromaDB (no server-side filter — filter in Python)
        qv = self.embedder.encode_query(query)
        n_res = min(self._CANDIDATE_K, self._col.count())
        chroma_res = self._col.query(
            query_embeddings=[qv],
            n_results=n_res,
            include=["distances"],
        )
        # hnsw:space=cosine → distance = 1 - cosine_similarity
        chroma_cos: dict[str, float] = {
            cid: 1.0 - dist
            for cid, dist in zip(chroma_res["ids"][0], chroma_res["distances"][0])
            if cid in self._by_id  # ignore video chunks that slipped through
        }

        # 2. Lexical: BM25 scores for all manual chunks
        bm_scores = self._bm25.get_scores(tokenize(query))
        bm_raw: dict[str, float] = {self._ids[i]: bm_scores[i] for i in range(len(self.chunks))}

        # 3. Build candidate set: top-BM25 ∪ top-Chroma, after applying filters
        filtered_ids = [
            cid for i, cid in enumerate(self._ids)
            if self._passes_filter(self.chunks[i], manual_id, system, vehicle_kw, profile)
        ]
        bm_top = sorted(filtered_ids, key=lambda c: bm_raw[c], reverse=True)[:self._CANDIDATE_K]

        # Apply Python-side filter to chroma results too
        chroma_filtered = {
            cid for cid in chroma_cos
            if self._passes_filter(self._by_id[cid], manual_id, system, vehicle_kw, profile)
        }
        candidates = set(bm_top) | chroma_filtered

        if not candidates:
            return []

        # 4. Normalise and blend
        cand_bm  = {c: bm_raw.get(c, 0.0) for c in candidates}
        cand_cos = {c: chroma_cos.get(c, 0.0) for c in candidates}

        def _norm(d):
            vals = list(d.values())
            lo, hi = min(vals), max(vals)
            rng = (hi - lo) or 1.0
            return {i: (v - lo) / rng for i, v in d.items()}

        bm_n  = _norm(cand_bm)
        cos_n = _norm(cand_cos)

        scored = []
        for cid in candidates:
            c = self._by_id.get(cid)
            if c is None:
                continue
            blended = alpha * cos_n[cid] + (1 - alpha) * bm_n[cid]
            if boost:
                blended = self._boost(query, c, blended)
            scored.append((cid, blended, cand_cos[cid], cand_bm[cid]))

        scored.sort(key=lambda x: x[1], reverse=True)

        out = []
        for cid, blended, cosine, bmraw in scored[:k]:
            c = self._by_id[cid]
            out.append({
                "chunk_id":      c["chunk_id"],
                "manual_id":     c.get("manual_id", ""),
                "manual_title":  c.get("manual_title", ""),
                "page_physical": c.get("page_physical", 0),
                "page_label":    c.get("page_label"),
                "section_title": c.get("section_title"),
                "system":        c.get("system"),
                "vehicle":       c.get("vehicle"),
                "has_diagram":   c.get("has_diagram"),
                "page_image":    c.get("page_image"),
                "viewer_url":    c.get("viewer_url", ""),
                "text":          c["text"],
                "score":         round(blended, 4),
                "cosine":        round(cosine, 4),
                "bm25":          round(bmraw, 3),
            })
        return out


# ----------------------------------------------------------------- grounding gate


_STOP = set("a an the of to for and or in on at by is are be with from this that "
            "how do i what where when which my your me it as you can not".split())


def _content_tokens(q):
    return [t for t in tokenize(q) if t not in _STOP and len(t) >= 2]


def gate(results, cos_floor=0.62, bm25_floor=8.0, coverage_floor=0.5, query=""):
    """ACCEPT only with real manual support. Semantic relevance is the primary
    authority; a lexical match can ALSO authorize, but only if the query's
    distinctive tokens literally appear in the chunk -- otherwise a high BM25 on
    filler words ("wifi password") would wrongly clear. Returns (decision, reason)."""
    if not results:
        return "REFUSE", "no chunks survived the applicability filter"
    top = results[0]
    if top["cosine"] >= cos_floor:
        return "ACCEPT", f"semantic match (cosine {top['cosine']:.2f} >= {cos_floor})"
    # lexical path: strong BM25 AND the query's content words are really present
    ctoks = _content_tokens(query)
    if ctoks and top["bm25"] >= bm25_floor:
        chunk_toks = set(tokenize(top["text"] + " " + (top.get("section_title") or "")))
        coverage = sum(t in chunk_toks for t in ctoks) / len(ctoks)
        if coverage >= coverage_floor:
            return "ACCEPT", (f"verified lexical match (bm25 {top['bm25']:.1f}, "
                              f"{coverage:.0%} of query terms present)")
        return "REFUSE", (f"cosine {top['cosine']:.2f} < {cos_floor}; bm25 high but only "
                          f"{coverage:.0%} of query terms present (keyword coincidence)")
    return "REFUSE", (f"best cosine {top['cosine']:.2f} < {cos_floor} and "
                      f"no verified lexical match")


def assemble_context(results):
    """Build the citation-bearing evidence block handed to the generator, plus
    the allow-list of chunk_ids the generated answer is permitted to cite."""
    lines, allowed = [], []
    for r in results:
        allowed.append(r["chunk_id"])
        pl = f" (printed p.{r['page_label']})" if r.get("page_label") else ""
        dia = "  [diagram on page]" if r.get("has_diagram") else ""
        lines.append(
            f"[{r['chunk_id']}] {r['manual_title']} \u2014 {r['section_title']} "
            f"\u2014 PDF p.{r['page_physical']}{pl}{dia}\n"
            f"    {r['viewer_url']}\n"
            f"    {r['text'][:600].strip()}"
        )
    return "\n\n".join(lines), allowed


def check_citations(answer_text, allowed_ids):
    """Structural grounding check the generator's output must pass: every
    [chunk_id] cited in the answer must be one that was actually retrieved.
    (Claim-level entailment is the generator LLM's job; this catches the most
    common failure -- a confident citation to something never retrieved.)"""
    cited = set(re.findall(r"\[([a-z0-9_]+_p\d{4}_\d{2})\]", answer_text))
    invalid = sorted(cited - set(allowed_ids))
    return {"cited": sorted(cited), "invalid": invalid, "ok": not invalid and bool(cited)}


# ----------------------------------------------------------------- CLI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="question to ask the library")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--embedder", choices=["local", "ollama"], default="local")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=0.5, help="dense weight in hybrid (0=BM25 only, 1=dense only)")
    ap.add_argument("--boost", action="store_true", help="experimental section/phrase rerank (off by default; net-negative on current eval)")
    ap.add_argument("--manual", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--vehicle", default=None)
    ap.add_argument("--cos-floor", type=float, default=0.62)
    ap.add_argument("--bm25-floor", type=float, default=8.0)
    ap.add_argument("--selftest", action="store_true", help="run a battery of in- and out-of-scope queries")
    args = ap.parse_args()

    lib = Library(args.out, make_embedder(args.embedder))

    def run(q):
        res = lib.retrieve(q, k=args.k, alpha=args.alpha,
                           manual_id=args.manual, system=args.system, vehicle_kw=args.vehicle, boost=args.boost)
        decision, reason = gate(res, args.cos_floor, args.bm25_floor, query=q)
        return res, decision, reason

    if args.selftest:
        battery = [
            ("in", "What is the throttle body to intake manifold bolt torque?"),
            ("in", "How do I remove and install the starter?"),
            ("in", "spark plug gap and type"),
            ("in", "engine oil capacity and specification"),
            ("in", "timing chain replacement procedure"),
            ("in", "where is the battery monitoring control module J367"),
            ("in", "part number 3C8 010 731"),
            ("in", "N80 valve location"),
            ("out", "how do I rebuild the rotary engine apex seals"),
            ("out", "What is the wifi password for the dealership?"),
            ("out", "best pizza topping combinations"),
            ("out", "what is the airspeed of an unladen swallow"),
        ]
        print(f"embedder: {lib.embedder.name}   chunks: {len(lib.chunks)}")
        print(f"gate floors: cosine>={args.cos_floor}  bm25>={args.bm25_floor}\n")
        ok = 0
        for kind, q in battery:
            res, decision, reason = run(q)
            expect = "ACCEPT" if kind == "in" else "REFUSE"
            good = decision == expect
            ok += good
            top = res[0] if res else None
            tl = (f"top: cos={top['cosine']:.2f} bm25={top['bm25']:.1f} "
                  f"[{top['manual_id']} p{top['page_physical']}]" if top else "no hits")
            print(f"{'PASS' if good else 'FAIL'}  [{expect}->{decision}]  {q}")
            print(f"        {tl}   ({reason})")
        print(f"\n{ok}/{len(battery)} expected decisions")
        return

    if not args.query:
        ap.error("provide a query or --selftest")
    res, decision, reason = run(args.query)
    print(f"# {args.query}")
    print(f"embedder={lib.embedder.name}  decision={decision}  ({reason})\n")
    if decision == "REFUSE":
        print(REFUSAL)
        return
    ctx, allowed = assemble_context(res)
    print("RETRIEVED EVIDENCE (citation context for the generator):\n")
    print(ctx)
    print("\nallowed citation ids:", allowed)


if __name__ == "__main__":
    main()
