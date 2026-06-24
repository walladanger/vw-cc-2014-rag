#!/usr/bin/env python3
"""Measure retrieval ranking quality against ground-truth target pages.
precision@1 = top hit is an accepted (manual_id, page); MRR = 1/rank of first accepted hit."""
import sys
import retrieve as R

# (query, {(manual_id, page), ...}) -- pages confirmed to literally contain the answer
EVAL = [
    ("torque for the starter mounting bolts",
     {("vw_cc_electrical_2018", p) for p in (29, 30, 31, 32)}),
    ("spark plug gap and type",
     {("vw_cc_2014_qsb", 169), ("vw_ea888_18_20_repair", 386)}),
    ("battery monitoring control module J367 removing and installing",
     {("vw_cc_electrical_2018", p) for p in (15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26)}),
    ("engine oil capacity and specification",
     {("vw_ea888_18_20_repair", 216)}),
    ("starter removing and installing",
     {("vw_cc_electrical_2018", p) for p in range(40, 56)}),
    ("generator mounting bolts",
     {("vw_cc_electrical_2018", 83)}),
]


def evaluate(lib, alpha, boost):
    p_at_1 = 0.0
    mrr = 0.0
    rows = []
    for q, gold in EVAL:
        res = lib.retrieve(q, k=10, alpha=alpha, boost=boost)
        ranks = [i for i, r in enumerate(res, 1) if (r["manual_id"], r["page_physical"]) in gold]
        first = ranks[0] if ranks else None
        hit1 = bool(first == 1)
        p_at_1 += hit1
        mrr += (1.0 / first) if first else 0.0
        top = res[0]
        rows.append((q, hit1, first, f"{top['manual_id']} p{top['page_physical']}"))
    n = len(EVAL)
    return p_at_1 / n, mrr / n, rows


def main():
    lib = R.Library("./out", R.make_embedder("local"))
    print(f"{len(EVAL)} eval queries\n")
    for label, boost in [("BASELINE (no boost)", False), ("WITH section+phrase boost", True)]:
        p1, mrr, rows = evaluate(lib, alpha=0.5, boost=boost)
        print(f"=== {label} ===  precision@1={p1:.2f}  MRR={mrr:.2f}")
        for q, hit1, first, top in rows:
            mark = "OK " if hit1 else ("v" + str(first) if first else "MISS")
            print(f"   [{mark:>4}] {q[:46]:<46} top: {top}")
        print()


if __name__ == "__main__":
    main()
