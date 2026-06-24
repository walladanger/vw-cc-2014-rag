# Retrieval + Grounding Gate (v1)

Enforces the core rule: **no manual citation, no technical answer.**

## What it does
1. Loads every `out/*/chunks.jsonl` into one index (4,571 chunks across 4 manuals).
2. **Hybrid retrieval**: BM25 lexical + dense cosine, per-query normalised and blended (`--alpha`).
3. **Grounding gate (pre-generation)** — ACCEPT only if:
   - dense cosine of the best hit >= `--cos-floor` (semantic relevance), OR
   - strong BM25 **and** the query's distinctive terms literally appear in the chunk
     (verified lexical — rescues exact part-number / component-code lookups).
   Otherwise REFUSE with the spec's exact wording.
4. **Citation context** assembled for the generator + an **allow-list** of chunk_ids.
5. **Grounding check (post-generation)**: `check_citations()` rejects any answer that
   cites a chunk_id that wasn't retrieved — catches fabricated citations.

## Embedder is pluggable (retrieval/gate logic identical either way)
- `--embedder local`  : sentence-transformers all-MiniLM-L6-v2 (offline; used for this demo)
- `--embedder ollama` : POST /api/embeddings `nomic-embed-text` on your TrueNAS Ollama (production)

Switch to your box with: `--embedder ollama` (defaults to http://localhost:11434).
Vectors are cached per-embedder under `out/.embcache/`, so re-embed only when chunks change.

## Run
    python retrieve.py --selftest                      # 12-case in/out-of-scope battery
    python retrieve.py "spark plug gap and type" -k 3  # real query -> evidence + citations
    python retrieve.py "wifi password" -k 3            # -> REFUSE

## Tunable gate floors (defaults shown)
    --cos-floor 0.45   --bm25-floor 8.0   (coverage_floor 0.5 in code)

## Ranking: measured, not assumed
`eval_ranking.py` scores precision@1 / MRR against ground-truth pages.

Finding: the **baseline hybrid ranker scores 1.00 / 1.00** on the current 6-query
eval set. A hand-tuned section-title + phrase boost (`--boost`) was tried and is
**net-negative** (fixes a starter-vs-muffler distractor on one phrasing but breaks
another query), so it is **OFF by default** and kept only as an experiment.

Two real notes:
  * One natural phrasing ("what is the torque for the starter mounting bolts?")
    ranks a *muffler* bolt (25 Nm) at #1 with the correct starter page at #2. This
    is NOT fatal: retrieval returns top-k, the generator reads all of them and cites
    the relevant chunk, and `check_citations()` validates it. A #1 distractor with
    the right answer in top-k still yields a correct, grounded answer.
  * The principled precision@1 fix is a learned cross-encoder reranker evaluated on a
    larger labeled set -- not hand-tuned heuristic weights. Grow `eval_ranking.py`'s
    EVAL list first; never tune ranking without measuring against it.

A real bug the eval surfaced and fixed: VW tables of contents use spaced dot leaders
(". . . .") that a naive "...." check misses, so TOC/index chunks weren't being
down-weighted. `_TOC_RE` now catches both.

## Note on the local-vs-ollama floor
Floors here are calibrated for MiniLM (384d). nomic-embed-text (768d) has a different
cosine distribution — re-run `--selftest --embedder ollama` and adjust `--cos-floor`
once on your box. The battery makes that a one-shot calibration.
