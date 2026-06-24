# Safety Architecture — Numeric Verification Layer

## The problem this solves
Retrieval + a citation check prove an answer *cites a real page*. They do **not**
prove the **number** in the answer matches the source. For torque specs that gap
is the difference between a bolt that holds and one that strips or snaps. The most
dangerous failure is silent: a generator that says "40 Nm" when the manual says
"40 Nm + 180°" produces a grossly under-torqued stretch bolt while looking
perfectly cited.

## Three layers, defense in depth
1. **Retrieval + grounding gate** (`retrieve.py`) — finds the right page or refuses.
2. **Numeric verification** (`specverify.py`) — THIS layer. Numbers are copy-only:
   extracted verbatim from the manual, and any number in an answer must match an
   extracted spec from a cited chunk character-for-character, or the answer is
   rejected.
3. **Human verification via the viewer** (to build) — every torque spec links to
   the rendered factory page so you confirm against the source before turning a wrench.

## What `specverify.py` guarantees (all tested on the real manuals)
- **Wrong number caught.** "75 Nm" mistyped as "57 Nm" → REJECT (not found in source).
- **Uncited number caught.** A value not present on any cited page → REJECT.
- **Dropped angle stage caught.** Source "40 Nm + 180°", answer "40 Nm" → REJECT
  with reason "DROPPED ANGLE STAGE". This is the critical stretch-bolt case.
- **Angle specs captured whole.** "20/40/60/100 Nm + 90°" sequences kept intact.
- **Tolerances captured whole.** "2.2 Nm ± 0.4 Nm" stays one spec, not two.
- **Stretch bolts flagged.** 60 specs carry a `replace_bolt` flag (single-use bolt,
  replacement mandatory) — surfaced alongside the torque.

Self-test: `python specverify.py selftest` → 5/5.

## Corpus audit (789 torque specs)
| Manual | specs | complex(angle) |
|---|---|---|
| QSB 2014 | 327 | 55 |
| Engine 1.8/2.0 TSI | 232 | 26 |
| Electrical | 200 | 0 |
| Maintenance | 31 | 0 |

Full per-spec export: `torque_spec_inventory.json` (review by hand; this is your
audit trail).

## Honest limitations (do not skip)
- **Fastener label coverage is ~60%.** The other 40% extract the correct value but
  without a clean "what it bolts to" label (dense table layouts). A value is only
  safe to act on WITH its fastener — so until coverage improves, the viewer page
  image is the required check.
- **`specverify` validates numbers, not clinical completeness.** It ensures a stated
  number is real and whole; it does not guarantee the answer found *every* relevant
  spec on a page. Always open the cited page.
- **Verification is only as good as extraction.** If a spec format exists that the
  regex doesn't recognize, the verifier can't protect a number it never saw. The
  regex is built against these four manuals; a new manual should be re-audited.
- **This is decision support, not authority.** The factory PDF, opened to the cited
  page, is the authority. Treat every torque value as "to be confirmed on the page."

## Hard rule for the generator (layer to build next, on your box)
The generator must be constrained so that:
  1. It states a torque value ONLY by copying a verified spec's `canonical()` string.
  2. Complex specs (`complex=True`) are shown verbatim — never reduced to the base number.
  3. `replace_bolt` specs always include the replacement instruction.
  4. Every answer runs through `verify_answer()`; a REJECT blocks the answer.
