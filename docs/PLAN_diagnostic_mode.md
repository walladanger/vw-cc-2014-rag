# CC Workshop — Plan: Diagnostic Mode (reasoning, not just retrieval)

**Audience:** this doc is written to be handed to another engineering agent (human or AI) with
no other context. It assumes only that the agent has this repo checked out.

**Status:** design only. No code has been written for this. Do not start building until the
Phase 1 environment work in `docs/PLAN_ui_parity_and_new_pages.md` is confirmed working on the
target machine — a reasoning layer on an unverified retrieval base means debugging two things
at once.

**Read first, in this order:**
1. `CLAUDE_CODE_HANDOVER.md` — the project's hard rules. The most important one:
   **"No manual citation, no technical answer."** This plan does **not** relax that rule.
   Section 3 below explains why it doesn't have to.
2. `app.py:301-425` — the current `/query` flow, which this plan extends.
3. `specverify.py` — the numeric gate. **Nothing in this plan changes it.**
4. `retrieve.py:522` — `gate()`, the grounding decision.

---

## 1. What this is for

Warwick's framing, in his words: *"i also dont want this to be an answer retrieval machine. It
also has to theorize and help problem solve. Infact, that will be one of its main purposes."*

His worked example, which this document uses throughout:

> *"I have an oil leak towards the front of my engine bay, I want the LLM to think about where
> it's coming from and why. Give me a checklist of things to check."*

That question is not a lookup. No single manual chunk answers it. It requires ranking
hypotheses, proposing tests that discriminate between them, and ordering the work so cheap
checks eliminate expensive ones first.

---

## 2. What the app does with that question today (trace it before changing it)

Follow the real code path for the oil-leak query:

1. `app.py:333` — `_expand(q)` appends jargon synonyms. "oil leak front engine bay" has no
   `_JARGON` entry, so the query passes through unchanged.
2. `app.py:334` — `lib.retrieve(retrieval_q, k=7, boost=True)`.
3. `app.py:335` — `gate(manual_results, query=retrieval_q)`.

Step 3 is where it fails. `gate()` (`retrieve.py:522`) accepts on either a semantic match
(`cosine >= 0.62`) or a verified lexical match (`bm25 >= 8.0` **and** ≥50% of query content
tokens literally present in the chunk). A symptom description matches neither reliably:
factory manuals are written as *procedures and specifications*, not as symptom descriptions.
There is no chunk whose text resembles "oil leak towards the front of my engine bay."

So the likely outcome is `REFUSE`, and `app.py:337-345` returns:

> "I cannot find this in the factory manuals I have indexed. Check the source PDF directly."

**This is the single most important observation in this document.** Diagnostic mode is not a
decorative feature bolted onto a working system. It is the correct handling of a branch the
app already reaches and currently serves badly. The `REFUSE` path is not a rare edge case for
symptom-shaped questions — it is the *expected* path.

A second problem compounds it: even on `ACCEPT`, `app.py:390` makes exactly **one**
`call_ollama` pass over a single retrieved context. There is no decomposition, so a question
requiring three different manual sections gets one retrieval and one shot.

---

## 3. The architecture: two channels

The apparent conflict between "theorize freely" and "no manual citation, no technical answer"
dissolves once you see that the rule governs **facts**, not **reasoning**. The risk was never
that the model thinks out loud. It is that a plausible-sounding theory smuggles in an uncited
torque figure.

So every diagnostic response is built from two clearly separated channels:

| | **Grounded channel** | **Reasoning channel** |
|---|---|---|
| Contains | torque values, clearances, capacities, part numbers, procedure steps | hypotheses, causal explanation, discriminating tests, ordering |
| Source | retrieved manual chunks, verbatim | generated |
| Citation | mandatory, `[Manual: {id}, Page {n}]` | none — labelled as inference |
| Gate | `specverify.verify_answer` + `gate()` | not spec-gated (see below) |
| May be wrong? | no — verbatim or refuse | yes, and must be presented as provisional |

**The property that makes this safe:** `specverify.verify_answer` (`specverify.py:165`) scans
the *entire* `answer_text` string for numbers. It does not care which channel a number appears
in. So a fabricated torque figure inside a hypothesis is caught by the existing gate with no
modification. The numeric firewall already composes with a reasoning mode.

**The rule for the reasoning channel:** it may discuss causes, symptoms, physical mechanism,
and test procedure. It may **not** state a spec. If a reasoning step needs a number, it must
either cite one from the grounded channel or say what to look up.

**UI requirement:** the two channels must be visually distinct in the rendered answer. A reader
must never have to guess whether a sentence is manual-derived or model-derived. This is a hard
requirement, not a nicety — it is the user-facing half of the safety rule.

---

## 4. Worked example: the oil leak

What a correct response looks like. Note how little of it needs retrieval at all.

**4.1 — Vehicle context check (before any retrieval).** See §5.1. A 2014 CC may be a 2.0 TSI
(EA888) or a 3.6 VR6. Front-of-bay oil leak sources differ substantially between them. The
system must be explicit about which variant it is reasoning about rather than silently
assuming.

**4.2 — Reasoning channel: the physics.** Costs no retrieval, and is most of the value:

- Oil travels down and rearward. The origin is the **highest, most forward** wet point, not
  the wettest area. Airflow at speed drags oil backwards, so visible residue is almost always
  downstream of the source.
- Pressurised sources (oil filter housing/cooler, pressure switch, turbo feed line on a
  turbocharged variant) leak mainly when running, often in a fan or spray pattern.
  Gravity/weep sources (valve cover gasket, cam cover) pool when parked.
  **One question — "does it drip on the driveway overnight, or only appear after a drive?" —
  splits the hypothesis space roughly in half before any tool is picked up.**

**4.3 — Reasoning channel: the checklist.** The ordering principle matters more than the
items: **each step must eliminate hypotheses, not merely inspect things.** Order by
(likelihood × cheapness):

1. Degrease the front of the engine, drive it, re-inspect. Nothing downstream is reliable on a
   dirty engine — otherwise you chase a months-old stain. Non-negotiable first step.
2. Cold start, inspect with light and mirror for the highest wet point.
3. UV dye if step 2 is ambiguous.
4. Overnight drip test on clean cardboard → pressurised vs. gravity.
5. Only then investigate the specific candidates.

**4.4 — Grounded channel.** Only once a candidate is identified does the manual get consulted,
and each retrieved fact is cited and spec-verified as today: component location, removal
procedure, gasket part number, bolt torque and sequence, any "replace after removal" warning
(`SYSTEM_PROMPT` rule 5).

**4.5 — Abstention, done well.** If the manuals cannot narrow it further, the response is not
"I cannot find this." It is: *"I can't discriminate further from the indexed manuals — here is
what to measure next, and what each result would rule out."* A diagnostic refusal that still
advances the work is the difference between a search box and something useful in a garage.

---

## 5. Components to build

### 5.0 Vehicle scoping — IMPLEMENTED, and why it came first

**Status: built and merged ahead of the UI work.** Warwick has three cars, and this turned
out to be a safety defect rather than a tidiness issue.

**The defect.** `specverify.verify_answer` proves a stated number was copied from a cited
chunk. It cannot tell whether that chunk *applies to the car being asked about*. Those are
orthogonal axes — provenance and applicability — and the app defended only the first. With
more than one vehicle in the index:

1. A query for "oil filter housing torque" retrieves a chunk for another car — high cosine,
   correct terminology, genuinely relevant-looking.
2. `gate()` returns ACCEPT on the semantic match.
3. `verify_answer` returns **VERIFIED**, because the number really is in the cited chunk.
4. The UI shows a green verified badge on a torque figure for the wrong car.

That is worse than an ordinary bug: the safety UI actively vouches for the wrong answer. A
refusal is safe; a confidently-verified wrong torque is what damages an engine.

**What existed already.** The whole applicability pipeline was built except its last link.
`ingest_manual.py` takes `--vehicle/--engine/--year`, stamps `vehicle`, `engine` and
`model_year` onto every chunk (`ingest_manual.py:393`), writes an `applicability` block to the
manifest (`:430`), and `build_vectordb.py:156,191` carries it into vector metadata.
`retrieve.py:_passes_filter` accepted a `vehicle_kw` argument. `app.py` simply never passed it,
so every query searched the entire index.

This was the third instance of one pattern in this codebase — **safety machinery built, wiring
omitted**. The others: `GAP_RE` defined and never called (§8), and `SYSTEM_PROMPT` asserting a
variant that nothing enforces (§5.1). Worth checking the last mile wherever a protection
appears to exist.

**Why substring matching was not enough.** Applicability is a hierarchy, not a boolean:
*this car → this platform → this marque → generic*. The real stamped values are
`"2014 VW CC 2.0T TSI"` (the default in both ingest scripts) plus `"VW"` and
`"VW (multi-model)"` for the shared DTC references. A substring filter on the full vehicle
string would have silently dropped those three generic documents; a filter on `"VW"` would
have admitted everything.

**What was implemented.** `retrieve.applies_to_vehicle(chunk, profile)`, applied through
`_passes_filter` and threaded through both `retrieve()` signatures. The rules, in order:

1. No active profile → applies. Filtering is opt-in.
2. Nothing stamped on the chunk → applies. **Fails open**, so indexes built before
   applicability was enforced cannot silently return nothing.
3. Generic reference (marque only, or explicitly multi-model) → applies unless it names a
   different marque, keeping shared DTC lists retrievable for any VW.
4. Otherwise the chunk names a specific vehicle and must match the profile. Engine is then
   checked the same way, excluding only when both sides name a specific engine that disagree.

`app.py` holds `VEHICLE_PROFILE`, defaulting to exactly what the ingest scripts stamp
(`2014 VW CC 2.0T TSI` / `CBFA`), overridable via `VW_VEHICLE` / `VW_ENGINE`, and disabled
entirely with `VW_VEHICLE_FILTER=0`. It is reported in `/status` and on every `/query`
response so the active car is visible rather than assumed.

**Verified against the real index composition:** 43/43 chunks retained for the current CC-only
index (no regression), 23 foreign chunks excluded once Audi material is added, and the
selection inverts correctly when scoped to the A4. Covered by
`tests/test_vehicle_applicability.py` (16 tests).

**Consequence for ingestion:** the `UnProcessed VW CC Manuals` batch is all CC and was always
safe. Other vehicles are safe to ingest too, provided they are stamped with their own
`--vehicle`/`--engine`.

Rule 2 fails open, which means an *unstamped* manual would match every car — the exact bleed
this filter exists to prevent, arriving through the back door. Since that trade is only
acceptable if nothing new can be ingested unstamped, `ingest_manual.py --vehicle` is now
**required**, and rejects a blank or whitespace value as well as a missing one (exit code 2,
with an error explaining why). `inspect` is unaffected, as it stamps nothing. Both PowerShell
batches already pass a non-blank value, so neither changes behaviour.

The fail-open rule and the required flag are two halves of one decision: retrieval stays
permissive so an existing index cannot be silently emptied, and ingest stays strict so the
permissiveness cannot be exploited by new material. Neither is safe without the other.

`--engine` remains optional. It is only consulted once a chunk's vehicle already matches, and
`_engine_agrees` treats a missing engine on either side as agreement, so an omitted engine
narrows nothing but cannot admit another car.

`ingest_guide.py` had the same hole in two places — a `"2014 VW CC 2.0T TSI"` default on both
the CLI flag and the batch loader — so a guide for another car would have been silently stamped
as the CC. Both are now closed. That file has **three** ways in, and all three are guarded:

| Entry point | Behaviour |
|---|---|
| `ingest` CLI | `--vehicle` required and non-blank; exit 2 |
| `ingest-batch` | validates every line **before any embedding work** and refuses the whole file, naming the offending line numbers and guide ids; exit 2 |
| `ingest_guide()` imported directly (`run_ingest_guides.py:396`) | guarded at the function, returns `False` with the reason |

The batch refuses as a whole rather than skipping bad entries, so a partial run cannot leave
unstamped chunks behind for someone to discover later.

The rule itself lives in `applicability.py`, which depends only on the standard library.
`ingest_manual.py` imports fitz at module scope while `ingest_guide.py` imports it lazily, so
neither can import the other without a side effect — and a safety check kept in two copies
eventually weakens in one of them. All 34 entries in `run_ingest_guides.py` already carry a
`vehicle`, so nothing existing breaks.

### 5.1 Vehicle context — and a correction to a stated assumption

`app.py:152` currently hardcodes the variant in the system prompt:

```
You are a factory-manual mechanic assistant for a 2014 VW CC 2.0T TSI.
```

This assumption is **implicit and unenforced**. Retrieval is not filtered by engine variant,
and the corpus may contain material covering several. So a VR6 chunk can be retrieved and
presented under a 2.0T TSI framing, with nothing in the pipeline objecting.

For lookup queries this is a latent risk. For diagnostic queries it is a direct correctness
problem, because **the variant drives hypothesis ranking** — the ranked list of likely leak
sources is materially different between EA888 and VR6.

Required:
- A vehicle-context object (engine code at minimum; mileage useful) held per session.
- The variant stated explicitly in any diagnostic response, so a wrong assumption is visible
  rather than buried in a prompt constant.
- Retrieval filtered or scored by variant applicability where chunk metadata supports it.
- Where the variant is unknown and materially changes the answer, **ask** rather than assume.

This is the same engine-code-qualifier problem that caused the DTC quick-start bulletin to be
held back from ingestion (see the exclusion notes in `ingest_unprocessed.ps1`). Same root
cause, and worth solving once.

### 5.2 Query router

Classify the incoming query before retrieval:

| Route | Meaning | Handling |
|---|---|---|
| `lookup` | "spark plug gap and torque" | current single-shot path, unchanged |
| `procedure` | "how do I change the oil filter housing" | current path, possibly multi-chunk |
| `diagnostic` | "oil leak at the front of the bay" | new path, §5.3–5.5 |
| `no_retrieval` | opinion / out of scope | decline without searching |

Keep it cheap: one short classification call. Default to `lookup` on ambiguity — that is the
conservative branch, since it applies the strictest gate.

### 5.3 Decomposition

A diagnostic query decomposes into sub-questions the manual *can* answer:

- "Where is the oil filter housing on this engine?"
- "What is the valve cover removal procedure?"
- "What is the cover bolt torque and sequence?"

Each sub-question is retrieved and gated **independently**, so each grounded fact carries its
own citation and its own pass/fail. The reasoning channel then connects them. This is the
mechanism that lets a question with no single answering chunk still produce a fully cited
response.

### 5.4 Hypothesis ranking

Output a **ranked** list of candidate causes, each carrying:
- a plain-language mechanism ("why this would produce this symptom"),
- a discriminating test (what result confirms or eliminates it),
- cost/difficulty, so ordering is defensible.

Flat, unranked lists of possible causes are what makes existing tools useless. The ranking and
the discriminating tests are the product.

### 5.5 Corrective retrieval hops

Allow a bounded number of re-queries (2–3) when the first retrieval comes back thin. Symptom
queries rarely find everything on the first pass — the useful search terms often only become
apparent after the first hypothesis set exists ("oil filter housing" was never in the user's
question). Bound it hard; unbounded loops on a local Ollama box will feel broken.

---

## 6. Integration points

All in `app.py` unless noted. This plan touches the **orchestration** layer only.

| Where | Change |
|---|---|
| `app.py:301` `/query` | Route on query class before retrieval. `lookup`/`procedure` keep today's exact path. |
| `app.py:335-345` `REFUSE` branch | The key change. On `REFUSE` **and** route `diagnostic`, enter the diagnostic path instead of returning the fixed refusal string. |
| `app.py:152` `SYSTEM_PROMPT` | Add a second prompt for the reasoning channel. Do **not** edit the existing rules 1-7 — they govern the grounded channel and are correct as written. |
| `app.py:390` `call_ollama` | Currently one call. Diagnostic mode needs several (decompose → per-sub-question → synthesise). Consider a thin orchestration helper rather than inlining. |
| `app.py:411-424` response JSON | Add fields; do not repurpose existing ones. The frontend reads `refused`, `verified`, `verify_findings`, `gate_reason`. |
| `retrieve.py:522` `gate()` | **Do not loosen the thresholds.** Diagnostic mode changes what happens *on refusal*, never what counts as grounded. |
| `specverify.py` | **No changes.** |

Suggested additional response fields:

```
"mode":         "lookup" | "procedure" | "diagnostic" | "no_retrieval",
"reasoning":    [ {claim, confidence, basis} ],   # reasoning channel, never spec-bearing
"hypotheses":   [ {cause, mechanism, test, rules_out, difficulty} ],
"checklist":    [ {step, purpose, eliminates} ],
"vehicle":      {engine_code, assumed: bool},
"abstain_reason": null | "no_retrieval" | "unsupported_claims" | "insufficient_evidence"
```

Enumerated `abstain_reason` values (rather than prose) make refusals **measurable**, so
over-refusal can be diagnosed instead of guessed at.

---

## 7. What NOT to do

- **Do not loosen `gate()` or `specverify` to make diagnostic answers easier to produce.** The
  entire design rests on those staying strict. If diagnostic mode needs a number it cannot
  verify, the correct output is to say what to look up.
- **Do not let the reasoning channel state specs**, even hedged ("roughly 20 Nm"). Rounding and
  paraphrasing specs is explicitly forbidden by `SYSTEM_PROMPT` rule 1, and a hedge is a
  paraphrase.
- **Do not present hypotheses as findings.** Ranked guesses are useful; ranked guesses wearing
  the styling of cited facts are dangerous.
- **Do not build this before Phase 1 passes on the target machine.**
- **Do not add the video corpus as part of this work.** Explicitly deferred by Warwick. The
  design should not depend on it.

---

## 8. Related defect (not part of this work, but adjacent)

`specverify.py:48` defines `GAP_RE` for millimetre values and **nothing calls it**.
`verify_answer` (`specverify.py:176`) iterates only `ANSWER_TORQUE_RE`, which matches torque
units (`Nm`, `ft-lb`, `lb-ft`, `in-lb`).

Consequence: on the project's own flagship demo question — *"What is the spark plug gap and
tightening torque?"* — the torque value is verified and **the gap value is not**. A stated mm
value is never scanned, never counted in `numbers_checked`, and leaves `all_ok` True.

`CLAUDE_CODE_HANDOVER.md` states the rule as covering "every torque value, **clearance**, or
spec". Clearances are in the rule but not in the code.

Deliberately not fixed here: the naive fix (verify every `\d+ mm`) would cause false
rejections, because manuals are full of mm values that are not specs — bolt diameters,
material thicknesses, dimensions in prose. Deciding which mm values constitute gate-worthy
claims is a design decision with a real false-reject cost, and it belongs to Warwick. It is
recorded here because it is the same class of problem this document is about: the gap between
the safety rule as stated and the safety rule as implemented.

---

## 9. Open decisions — get Warwick's answer; don't guess silently

1. ~~**How is engine variant established?**~~ **RESOLVED.** Warwick confirmed: single user,
   three cars, and cross-vehicle bleed is a problem even with one user. Decided:
   - Retrieval is scoped by a **vehicle profile**, enforced in `retrieve()` — the only layer
     that sees every candidate chunk. Implemented; see §5.0.
   - The profile currently comes from `VW_VEHICLE` / `VW_ENGINE` with defaults matching the
     ingest scripts. **The intended source is an OBD scan import**, which decodes the VIN to
     variant, engine code, model year and market in one step — with three cars, typing that
     per session is how mistakes get made.
   - Identity is keyed on **`safe_vehicle_id(vin, salt)`** (`vag_pipeline/common.py:62`), not
     the raw VIN. That function already exists and already keys parsed scans at
     `diagnostics.py:91`, so scans, conversations and service history can share one
     identifier. A raw VIN is not a secret — it is readable through the windscreen and printed
     on the V5C — and this repo's existing convention is to redact it (`redact_vins`), so
     making it the primary key would reverse that stance for no benefit.
   - **A VIN identifies a car, not a user.** One user has many vehicles (Warwick has three),
     so conversation history is scoped to a **(user, vehicle)** pair, with the vehicle half
     doing the technical isolation.
   - Import is **not** a hard gate on first run. Requiring a scan before a spark-plug lookup
     is hostile. Variant is required before *diagnostic* mode, where it drives hypothesis
     ranking; lookups do not need it.

   Still open: the import UI itself, and whether the profile persists to a config file or is
   derived from the most recent scan. Interacts with open decision 5 in
   `docs/PLAN_ui_parity_and_new_pages.md` (the Car Maintenance page's data model).
2. **Latency budget.** Diagnostic mode means several sequential Ollama calls where lookup means
   one. On a local box that may be 30-60s+. Acceptable, or should it stream partial results
   (hypotheses first, grounded detail as it arrives)?
3. **Does diagnostic mode get its own UI view, or render inline in chat?** A ranked hypothesis
   list with per-item tests is not shaped like a chat answer. This interacts with Phase 2 of
   the UI plan — decide before building either.
4. **How much may the reasoning channel rely on general automotive knowledge not in the
   corpus?** The oil-leak physics in §4.2 is sound general mechanical reasoning, not in any
   indexed manual. Recommendation: **allow it, labelled as inference, with specs still barred.**
   But this is the philosophical centre of the feature and Warwick should decide it explicitly
   rather than have it settled by implementation accident.
5. **Should `vag_pipeline` diagnostic data feed hypothesis ranking?** Real DTCs, freeze-frame
   and measurement blocks would sharpen ranking considerably. Depends on open decision 6 in the
   UI plan.

---

## 10. Acceptance criteria

1. The oil-leak question returns a ranked hypothesis list and an ordered checklist, not
   "I cannot find this in the factory manuals I have indexed."
2. Every spec in that response carries a citation and passes `specverify`.
3. Reasoning and grounded content are visually distinguishable in the UI.
4. The engine variant used for ranking is stated, and flagged when assumed rather than known.
5. `lookup` queries behave **exactly** as before — same path, same gate, same verification.
   Regression-test "What is the spark plug gap and tightening torque?" against the pre-change
   output.
6. A question with genuinely no support still abstains, with an enumerated reason and a
   next-measurement suggestion.
7. No change to `specverify.py`; no threshold change in `retrieve.py:gate()`.

---

## 11. On the source material

This design was prompted by *"Building a RAG Pipeline for 10M+ Documents With Near-Zero
Hallucination"* (Fareed Khan, June 2026), which Warwick supplied.

**Taken from it:** routing, query decomposition, bounded corrective hops, claim-level
verification for prose, the chain-of-verification repair pass, and enumerated abstention
reasons.

**Deliberately ignored:** MinHash LSH near-duplicate removal, LanceDB disk-scaled ANN, vLLM
serving, H100-class hardware, a 32B generator with 4B reranker/embedder. That article targets
10M+ documents; this app indexes on the order of 50 manuals on a single Windows machine
running Ollama. Adopting its infrastructure would add substantial complexity for no benefit at
this scale.

**Where this repo is already ahead of it:** the article's faithfulness judge is an LLM scoring
claims against a threshold. For numeric specs, `specverify`'s exact symbolic matching on
(value, normalised unit, angle stages) is strictly stronger — deterministic, no model in the
loop, and its `DROPPED ANGLE STAGE` diagnosis catches a failure mode (a torque-plus-angle spec
silently losing its angle stage) that a similarity score would wave through. Do not replace it
with an LLM judge.

The article's genuinely additive idea for this codebase is **claim-level checking of prose**.
`specverify` gates numbers; nothing currently gates a sentence like "this engine is
interference" or "that fastener must be replaced whenever removed". Those can be badly wrong
and are entirely unchecked today. That belongs alongside the numeric gate — never replacing it.
