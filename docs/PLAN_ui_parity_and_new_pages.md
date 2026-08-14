# CC Workshop — Plan: Restore the Original Look, Fix the Local Build, Add Two New Pages

**Audience:** this doc is written to be handed to another engineering agent (human or AI) with
no other context. It assumes only that the agent has this repo checked out.

**Repo:** `walladanger/vw-cc-2014-rag`, branch: work off `main` (or whatever branch you're
handed) and commit incrementally.

**Read first, in this order, before touching code:**
1. `README.md` — how to run the app in every mode (desktop / web / Docker).
2. `CLAUDE_CODE_HANDOVER.md` — the project's hard rules and architecture. The most important
   rule in the whole codebase: **"No manual citation, no technical answer."** Every torque
   value, clearance, or spec the assistant states must be verbatim-verified against a cited
   factory-manual chunk (`specverify.py`). Nothing in this plan touches that logic — this is a
   UI/build/scaffolding plan only.
3. `HANDOFF.md`, `RETRIEVAL_README.md`, `SAFETY_ARCHITECTURE.md` — deeper technical notes,
   only needed if something breaks during the environment work in Phase 1.

---

## 0. What's actually going on (root-cause diagnosis — read before doing anything)

Warwick attached two screenshots and said the current app (launched via an old `launch.bat`
shortcut) "doesn't look the same" as an earlier working iteration. Investigation of this repo
found the exact explanation, and it's two **separate** problems:

### Problem A — the screenshots are two *different* images that already exist in this repo
- `docs/cc-workshop-concept.png` is **pixel-for-pixel identical** to the first screenshot
  Warwick uploaded (the fully-populated "spark plug gap" answer with pill-style status badges,
  numbered source cards, a confidence meter, message action icons, etc.). Filename says it
  all: this is a **concept/design mock**, not a screenshot of a working build.
- `docs/cc-workshop-render.png` is a screenshot of the **actual current app** — i.e. what you
  get today from `templates/index.html` + `static/app.css` + `static/app.js`. It is visibly
  simpler: no status pills, no gear icon, no message action row, no confidence meter, plain
  `<iframe>` PDF viewer instead of a page-image/text toggle.
- The second screenshot Warwick uploaded (the "Manual Integrity Review" side-by-side page
  comparison tool) **does already match** the real, working `templates/manual_review.html` /
  `static/manual-review.css` / `static/manual-review.js`. That page is not part of this
  problem — treat it as a working reference for visual polish, and only regression-test it.

**Conclusion:** the chat page was designed once (the concept mock) and only partially built.
Pulling the latest code from GitHub will **not** make the real app look like the concept image
— that gap is real, unbuilt UI work, cataloged in detail in Phase 2 below.

### Problem B — the local machine is likely running a stale, disconnected copy
The `.lnk` shortcut Warwick uploaded points at:
```
C:\Users\Desktop\OneDrive\Documents\Projects\vw_rag_phase2b\launch.bat
```
This repo is named `vw-cc-2014-rag` on GitHub — a different folder name. `vw_rag_phase2b` is
an **older local folder from before the GitHub migration**, and it predates recent commits
(ChromaDB vector store, portable data folder, native title-bar coloring — see `git log`).
Several files in this repo still contain hardcoded references to that old path, which is
itself evidence of the rename/migration and a source of future confusion:
- `manual_review.py:562` — the `--corpus` CLI default falls back to
  `C:\Users\Desktop\OneDrive\Documents\Projects\vw_rag_phase2b\out` when `VW_RAG_OUT` isn't set.
- `docs/VAG_DATABASE.md:14` — example `$corpus` path.
- `ingest_all.ps1:3` — a comment saying "Run from: ...vw_rag_phase2b\".
- `CLAUDE_CODE_HANDOVER.md:31,420` — references to `vw_rag_phase2b.zip`.

**Conclusion:** running the app from the old folder means Warwick may be looking at stale code
*in addition to* the real, never-closed concept/build gap in Problem A. Both need fixing;
neither one alone explains everything.

---

## Phase 1 — Get a correct, current local build running (environment parity)

Do this first and confirm the baseline before making any UI changes, so later visual diffs are
attributable to your Phase 2 work and not leftover environment drift.

1. **Do not delete the old folder yet.** `vw_rag_phase2b` may contain a built `out/` folder
   (the indexed manuals — ChromaDB, chunks, diagrams) and a `.env` that are not in git
   (`out/` and `.env` are gitignored — see `.gitignore`). Locate and preserve:
   - `vw_rag_phase2b\out\` (or wherever `VW_RAG_OUT` pointed)
   - `vw_rag_phase2b\.env`
   - any manual PDFs not yet backed up elsewhere
2. Get a clean, current checkout of this repo on the Windows machine, e.g.
   `C:\Users\Desktop\OneDrive\Documents\Projects\vw-cc-2014-rag` (matching the GitHub repo
   name, to avoid future path confusion). `git pull` if it already exists locally; clone fresh
   if it doesn't.
3. Copy the preserved `out/` folder into the new checkout (either directly beside `desktop.py`
   as `out/`, which `desktop.py`'s `_app_data_dir()` prefers when present, or into
   `%LOCALAPPDATA%\CC Workshop\out` — check `desktop.py:29-38` for the exact precedence before
   picking one, and only use one of the two to avoid ambiguity). Copy `.env` if one existed.
4. Update or recreate the desktop shortcut so it points at the **new** folder's `launch.bat`,
   and remove/retire the old shortcut so it can't be launched by accident again.
5. Set up the environment exactly as the existing scripts do — don't invent a new process:
   - Desktop/native: `pip install -r requirements-desktop.txt` (or run `build_windows.ps1`,
     which creates the venv for you).
   - Browser/dev mode: `run_web.ps1` (creates its own venv, installs `requirements.txt`, runs
     `web_server.py`).
6. Confirm Ollama is running locally and has the two models `README.md` calls out:
   `ollama pull qwen3.6:latest` and `ollama pull nomic-embed-text`. Confirm with `ollama list`.
7. Launch both entry points and sanity-check `/status`:
   - `launch.bat` → native window should open, `/status` (visible via dev tools if needed, or
     just check the topbar) should report the real manual/chunk counts and `Ollama offline`
     should flip to a model name once Ollama is reachable.
   - `python web_server.py` → browser at `http://localhost:5000`, same checks.
8. Fix the stale path references found above so this doesn't recur:
   - `manual_review.py:562` — change the hardcoded fallback default to something
     path-agnostic (e.g. `Path(__file__).resolve().parent / "out"`) rather than another
     hardcoded absolute Windows path, since the whole point of `VW_RAG_OUT` is portability.
   - `docs/VAG_DATABASE.md:14-15` — update the example paths to the new repo folder name.
   - `ingest_all.ps1:3` — update the comment.
   - Leave `CLAUDE_CODE_HANDOVER.md` alone — it's a dated historical handover document, not
     live instructions; editing it isn't in scope here.

**Acceptance for Phase 1:** app launches from the new, correct folder in both desktop and
browser modes; `/status` reports `ready: true` with the real manual/chunk counts; a real
question (e.g. "What is the spark plug gap and tightening torque?") returns a grounded,
cited answer with working PDF citation links.

---

## Phase 2 — Close the visual gap between the real app and `docs/cc-workshop-concept.png`

This is the actual "make it look like it did" work. Everything below is scoped to
`templates/index.html`, `static/app.css`, `static/app.js`, and (where noted) small additions
to `app.py`. **Nothing here should touch `retrieve.py`, `specverify.py`, or the grounding gate
logic** — this is presentation only, wired to data that mostly already exists.

Work through this as a checklist. For each row, "current" cites the exact place in the code
today; "target" describes the concept mock; "change" is what to build.

### 2.1 Top bar (`.topbar` in `app.css:44-53`, markup in `index.html:39-50`)
- **Current:** plain text status items separated by vertical rules (`.status-item`), no icon
  buttons on the right edge.
- **Target:** rounded pill/chip badges — green outlined pill for "All numeric specifications
  verified" with a check icon, an Ollama status chip with a small cloud/status-dot icon, an
  "Indexed manuals: N" chip with a book icon — plus a settings gear icon button at the very
  right edge of the bar.
- **Change:** restyle `.status-item` into pill chips (border-radius, border, padding, icon +
  text), keep the existing IDs (`#ollama-status`, `#manual-count`) and `app.js:loadStatus()`
  logic as-is — only the CSS/markup wrapper changes. Add a gear icon `<button>` in the topbar
  that opens the same `#settings-view` the rail's "Settings" button opens (reuse the existing
  view-switch handler in `app.js:231-238`, just trigger a click on the Settings rail button
  from the new gear button, or factor the "switch to view" logic into a small reusable
  function).

### 2.2 Left rail (`.rail` in `app.css:29-41`, markup in `index.html:12-36`)
- **Current:** 4 nav buttons — Chat, Library, Verify (links to `/manual-review/`), Settings.
  Footer is a single small status line (dot + one word: Starting/Ready/Setup/Offline).
- **Target:** concept mock shows 3 nav icons (Chat, Library, Settings) and a two-line footer —
  bold "Ready" + muted "Index up to date" — with a separate "« Collapse" affordance below it.
- **Decision needed (see Open Decisions below) before building this:** the concept mock
  doesn't show a "Verify" nav icon at all, but it's a real, working, already-built safety
  feature (`/manual-review/`) — recommend **keeping** it, just restyled to match the other
  three icons, rather than deleting a working feature to match a mock that predates it.
- **Change:**
  - Restyle the rail footer into two lines (bold state word + muted detail line), driven by
    the same `#rail-state` logic in `app.js:29-67` (add a second `<small>` for the detail
    line, e.g. "Index up to date" when ready, or the actual error string when not).
  - Add a collapse control that shrinks the rail to icon-only or hides labels, persisting the
    collapsed state in `localStorage` so it survives reloads. This is new, currently
    nonexistent behavior — keep it simple (toggle a class on `.app-shell` that changes the
    grid-template-columns rail width, per the existing `@media (max-width: 760px)` pattern
    already in `app.css:154-174` as a model).

### 2.3 Chat messages — timestamps + action row (`app.js:69-130`, CSS `app.css:77-108`)
- **Current:** `appendUser()` and `appendAnswer()` render no timestamp and no action buttons.
- **Target:** every message (user bubble and answer card) shows a timestamp (e.g. "10:24 AM");
  every answer card has a bottom action row: thumbs-up, thumbs-down, bookmark, copy, share.
- **Change:**
  - Add `new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})` timestamp
    markup to both `appendUser()` and `appendAnswer()`.
  - Add an action row to the answer card template in `appendAnswer()`. Wire real behavior, not
    decoration (see Open Decisions — recommended defaults):
    - **Copy:** `navigator.clipboard.writeText()` of the answer text — trivial, do this
      unconditionally.
    - **Share:** `navigator.share()` if available, else fall back to the same clipboard copy
      (include the answer + first citation's `viewer_url`).
    - **Thumbs up/down + bookmark:** POST to a new small Flask endpoint (e.g.
      `POST /feedback`) that appends a JSON line to `OUT_DIR/feedback.jsonl` — query, answer,
      citations, rating, timestamp. This gives the buttons real effect without inventing a
      user-account system. No UI is required to *read* this data back yet — just capture it.

### 2.4 Answer header badge (`app.css:80-90`, `app.js:109-130`)
- **Current:** already has the green check seal, "Grounded answer" / "Sourced from factory
  manuals" text, and a `verify-label` text on the right ("All numeric specifications verified"
  or "Source-grounded response"). This is close to the concept already.
- **Change:** restyle `.verify-label` into a small pill badge with a check icon to match the
  concept's top-right badge treatment (cosmetic CSS-only change; the underlying `verified`
  boolean logic in `app.py:query()` / `app.js:appendAnswer()` is already correct).

### 2.5 Safety warning callout (`app.css:91-92`)
- Already implemented and already close to the concept (amber box, triangle icon, "Safety
  warning" heading). Only touch this if a side-by-side comparison shows a real visual diff —
  don't rebuild something that already works.

### 2.6 Factory manual source cards (`app.css:93-98`, `app.js:87-98`)
- **Current:** `.source-card` shows title, a `section_title` (or falls back to `manual_id`),
  and the page number — no numbered index, no breadcrumb hierarchy styling.
- **Target:** each row has a numbered circular badge (1, 2, 3…), a breadcrumb-style title
  ("Maintenance → Spark plugs"), a manual/edition subtitle line, and the page number
  right-aligned.
- **Change:** add an index badge in `sourceCards()` (`app.js:87-98`) using the array index.
  For the breadcrumb: check whether `section_title` in the retrieval output already contains a
  hierarchy separator (inspect a few real chunks via `retrieve.py "spark plug gap" -k 3`) —
  if it doesn't, this is cosmetic-only (just style what's already there) rather than a data
  change; don't invent hierarchy data that doesn't exist in the chunks.

### 2.7 Composer (`app.css:110-117`, `index.html:73-78`)
- **Current:** textarea + single send button.
- **Target:** a "+" attach button and a filter/sliders icon button to the left of the
  textarea, in addition to the send button.
- **Change:** add the two buttons to the markup and CSS. Scope their real behavior narrowly —
  don't over-build:
  - "+" (attach): out of scope for this pass — there's no file-upload-to-chat feature in the
    backend. Render it **disabled** with a tooltip like "Coming soon" rather than faking
    functionality, or omit it and flag this as an Open Decision (see below).
  - Filter/sliders icon: could open a small popover for retrieval options that already exist
    as query-time parameters in `app.py:query()` (e.g. `k`) — recommend deferring this too
    unless Warwick wants query controls exposed. Same treatment: disabled/deferred, not faked.

### 2.8 Evidence panel (`app.css:119-128`, `index.html:83-101`, `app.js:185-207`)
This is the biggest single item in Phase 2.
- **Current:** a `source-summary` block (title + section) followed by a live `<iframe>`
  pointed at `/pdf/{manual_id}#page={n}` (the browser's native PDF viewer), and an "Open full
  PDF" button. This is genuinely more capable than a static image (real pagination, real
  selectable text, zero extra rendering cost) — it works today.
- **Target:** a "Page | Text" segmented tab control, a rendered page view, a page navigator
  (‹ current/total › + external-link icon), and a "Confidence" meter (progress bar + High/
  Medium/Low label + info icon + "Matched content in N source(s)" caption).
- **What's realistically buildable without new backend work, and what needs it:**
  - **Confidence meter — buildable now.** `retrieve.py`'s `gate()` function already computes a
    cosine similarity score per result (`retrieve.py:522-542`, `top["cosine"]`). Have
    `app.py:query()` return this score (bucket it: e.g. `>=0.75` High, `>=0.62` Medium, else
    Low — reuse the existing `cos_floor` from `gate()` as the Medium/Low boundary so the
    bucketing logic doesn't drift from the actual grounding gate) alongside each citation, and
    a count of matched sources (`len(citations)`), then render the meter in the Evidence panel
    from that data.
  - **Text tab — buildable now.** The chunk text already exists in `chunks.jsonl` / is already
    assembled into `context_text` server-side. Return the cited chunk's raw text alongside its
    citation in `/query`'s response and render it in a "Text" tab — no new extraction work.
  - **Page tab / page-image render — partially buildable.** `ingest_manual.py` only renders a
    full-page PNG for diagram or OCR-needed pages (`ingest_manual.py:346-408`,
    `if page_image and (has_d or ocr)`), not for every page. **Recommendation: do not replace
    the working `<iframe>` PDF viewer.** Keep it as the default "Page" tab content (it already
    covers 100% of pages, with real pagination) and layer the new Page/Text tab control, page
    counter, and confidence meter *around* it, rather than trying to reproduce a static-image
    page view that only exists for a subset of pages. This preserves full functionality while
    still closing the visual gap.
  - **Page navigator (‹ N/total ›):** the PDF `<iframe>` doesn't expose its current page or
    page count to JS by default. Get the total page count from the manual's manifest
    (`page_count`, already present per `/library`'s response) and drive prev/next by rewriting
    the iframe's `#page=` hash fragment — accept that "current page" in the navigator reflects
    the citation's page, not live sync with in-iframe scrolling, and say so if asked; don't
    silently fake it.

### 2.9 Empty state (welcome screen, `app.css:62-75`, `index.html:56-69`)
- **Do not blindly copy the concept's empty-state copy.** The concept mock's empty state
  ("Add Manuals" button, "1. Add manuals / 2. Index content / 3. Ask questions") describes an
  in-app manual-upload flow that **does not exist** in this codebase — manuals are added via
  the command-line ingestion scripts (`ingest_manual.py`), not a UI upload button. The current
  real copy ("Copy an existing processed `out` folder into the data location below, or run the
  ingestion tools...") is accurate to how the app actually works.
  **Recommendation:** keep the real, accurate copy and data-path display; only apply the new
  visual language (icon style, spacing, typography) from the concept, not its (currently
  fictional) onboarding flow. If Warwick specifically wants in-app manual upload as a real
  feature, that's new scope beyond this plan — flag it, don't build it silently here.

### 2.10 Color/typography pass
- Current tokens (`app.css:1-19`) — `--bg:#080b0f`, `--blue:#3888ff`, `--green:#47d778`,
  `--amber:#ffb21c` — already closely match the concept's dark theme and are also the exact
  blue used for the native window title bar in `desktop.py:92` (`0x00FF8838` = BGR of
  `#3888ff`). Don't rebuild the palette from scratch; only nudge specific values if a
  side-by-side screenshot comparison (Phase 4) shows a clear, specific mismatch.

---

## Phase 3 — Two new pages: Car Maintenance and Car Data Files

Warwick asked for these as new nav destinations with details "worked out later." Build them as
**real, wired, empty placeholders** — not fake static HTML — so filling in the real data model
later is additive, not a rebuild.

1. **Nav + view scaffolding** — follow the exact existing pattern, no new JS plumbing needed:
   - Add two `<button class="rail-button" data-view="maintenance">` / `data-view="data-files"`
     entries to the rail in `index.html`, matching the style of the existing Chat/Library
     buttons (icon + label).
   - Add two `<section class="view utility-view" id="maintenance-view">` /
     `id="data-files-view">` blocks, reusing the `.utility-header` / list / empty-state CSS
     already defined for the Library view (`app.css:130-142`).
   - The existing rail-button click handler (`app.js:231-238`) is generic — it already works
     for any `data-view` whose id matches `#{view}-view`. Only add a lazy-load call if the new
     pages fetch data on first view, following the existing
     `if (button.dataset.view === "library") loadLibrary();` pattern.
2. **Backend routes** — wire real endpoints now, even though they return placeholder data,
   mirroring `app.py`'s existing `/library` route shape:
   - `GET /maintenance` → `{"records": [], "error": null}` for now.
   - `GET /data-files` → `{"files": [], "error": null}` for now.
   - Frontend renders an empty-state message ("No maintenance records yet." /
     "No data files yet.") using the same `.empty-library`-style component already in `app.css`
     — don't invent new empty-state styling.
3. **Do not build past the stub without sign-off.** Specifically do not implement file upload,
   editing, or a maintenance-log data model yet — see Open Decisions below for what to ask
   Warwick before extending either page further. This repo already has a relevant backend
   that either page could eventually draw from — surface it as an option, don't wire it yet:
   - `vag_pipeline/` (see `docs/VAG_DATABASE.md`) ingests decoded iCarsoft OBD2 reports (DTCs,
     coding/adaptation snapshots, `measurement_samples`) into CSV/Parquet/Postgres tables and
     Qdrant collections, with VIN redaction already built in
     (`vag_pipeline/common.py:redact_vins`). This is a very natural real data source for "Car
     Data Files" (and partially for a maintenance history view) once Warwick confirms that's
     the intent.
   - For the maintenance page specifically there is also a third, non-repo source — VW's
     per-VIN Digital Service Schedule, reachable free through the erWin portal. See Open
     Decision 5(c) for what it is and the caveats that come with it.

---

## Phase 4 — Verification checklist (run all of this before calling the work done)

1. `python specverify.py selftest` → must be 5/5.
2. `python retrieve.py --selftest` → must be 12/12 (and `--selftest --embedder ollama` once
   Ollama + `nomic-embed-text` are confirmed, re-calibrating `--cos-floor` only if it fails —
   see `HANDOFF.md` for the calibration procedure; don't touch this casually).
3. End-to-end chat flow with Ollama running: ask all three starter questions from the welcome
   screen; confirm citations open correctly in the Evidence panel; confirm the confidence
   meter renders sensibly for a strong match; confirm the REFUSE path (ask something clearly
   out of scope) still shows the refusal copy correctly; confirm the "Ollama unreachable" path
   (stop Ollama, ask a question) still shows the existing warning message.
4. `/manual-review/` — regression check only. This page already matches the second screenshot
   Warwick provided; just confirm nothing in Phase 2's shared CSS accidentally broke it (it has
   its own stylesheet, `manual-review.css`, but shares the same design tokens conceptually).
5. New Maintenance / Data Files views: confirm they render, don't throw JS errors with empty
   data, and are reachable/consistent whether or not the manual library is ready (recommend:
   always visible/enabled, since they're independent of the RAG library's ready state).
6. Responsive check at the two existing breakpoints (`app.css:147-174`, 1050px and 760px) —
   confirm the new rail items and topbar changes behave correctly on narrow widths, same as
   the existing nav items.
7. Rebuild the native app (`build_windows.ps1`) and do a final pass via the actual
   `dist\CCWorkshop.exe` / `launch.bat`, not just the dev Flask server — the title bar coloring
   and `pywebview` chrome only show up in the real native build.
8. **Take a fresh screenshot of the running app in the same state as the concept mock** (the
   answered "spark plug gap" question) and do a side-by-side visual diff against
   `docs/cc-workshop-concept.png`. Once satisfied, replace `docs/cc-workshop-render.png` with
   the new screenshot so this exact confusion — "why doesn't it match?" — is easy to catch
   early next time the two drift apart again.

---

## Phase 5 — Housekeeping while in there

- Confirm the Phase 1 stale-path fixes (`manual_review.py:562`, `docs/VAG_DATABASE.md:14-15`,
  `ingest_all.ps1:3`) are committed.
- Update `README.md` if Phase 2/3 introduced any new env vars, routes, or setup steps (e.g. a
  new `/feedback` endpoint, new `/maintenance` and `/data-files` routes).
- Confirm `out/`, `.env`, and any manual PDFs never got staged (`git status` before every
  commit — they're gitignored, but double-check nothing slipped in via `git add -A`).

---

## Open decisions — get Warwick's answer on these before/while building; don't guess silently

1. **Keep the "Verify" (manual-review) rail icon even though the concept mock omits it?**
   Recommendation: yes, keep it, restyled to match. It's a real, already-working safety
   feature; the concept mock likely just predates it or omitted it for the mock's simplicity.
2. **Evidence panel "Page" tab: replace the working PDF `<iframe>` with a static page-image
   viewer, or keep the iframe and add the tab/navigator/confidence chrome around it?**
   Recommendation: keep the iframe (Phase 2.8) — it already covers every page with real
   pagination; a static image only exists for diagram/OCR pages today.
3. **How functional should the message action row be (thumbs up/down, bookmark, copy,
   share)?** Recommendation (Phase 2.3): copy and share fully functional immediately (trivial,
   client-side); thumbs/bookmark logged to a simple local `feedback.jsonl` file (no UI to read
   it back yet, just capture); nothing here should be purely decorative given "everything has
   to work and be functional."
4. **Composer's "+" attach button and filter/sliders icon — build real functionality, or ship
   disabled/deferred?** Recommendation: ship disabled with a "coming soon" tooltip, or omit
   until there's a real feature (file-attach to chat, or exposed retrieval params) to back
   them — don't fake functionality that doesn't exist.
5. **Car Maintenance page — what should it actually track once past the stub?** A candidate
   minimal schema to propose to Warwick: `service_date`, `mileage`, `item`, `notes`,
   `next_due`. Three possible sources for that data:
   - **(a) User-entered** — a simple local log file the page writes to. Lowest effort, but
     the data is only as good as what gets typed in, and it starts empty.
   - **(b) Derived from `vag_pipeline`** — reuse the decoded iCarsoft OBD2 reports already
     being ingested (see `docs/VAG_DATABASE.md`). Gives real vehicle data, but diagnostic
     scans are not a service history: they capture faults and adaptation state at a point in
     time, not "what work was done when."
   - **(c) Imported from VW's Digital Service Schedule** — VW maintains a per-VIN electronic
     service record, and it can be reached for free (no flatrate subscription) through the
     erWin portal. The procedure is documented in `EN_VW_CR4688.pdf` in Warwick's manuals
     folder: log into the brand's erWin store, enter the VIN, and generate a maintenance
     table / service certificate. This is the closest thing to a real, authoritative service
     history for the actual car.

   Notes on (c), which are the reason it needs a decision rather than just being the obvious
   winner:
   - **It is not an API.** Retrieval is a manual, interactive web session — log in, enter the
     VIN, read or print the result. So the app can offer an *import* (upload/paste the
     generated table, then parse it), not a live sync. Anything that looked like automatic
     background refresh would be misrepresenting how the data actually gets there.
   - **VIN handling.** A VIN is the lookup key, so this path necessarily puts one into the
     app's data path. `vag_pipeline/common.py:redact_vins` already exists and defines how
     this repo treats VINs — any import flow must go through the same redaction rather than
     inventing a second, looser convention.
   - **Scope.** `EN_VW_CR4688.pdf` is marked INTERNAL and describes accessing records for a
     vehicle you own. Treat it as a route to Warwick's own service history, not as content to
     ingest, redistribute, or bulk-query. (The PDF itself is deliberately excluded from the
     RAG index — it is portal documentation with no vehicle content; see the exclusion list in
     `ingest_unprocessed.ps1`.)

   These are not mutually exclusive: (c) as the initial import to populate real history, with
   (a) as the ongoing manual log for work done since, is a plausible combination. **Get
   Warwick's answer before building past the Phase 3 stub** — this materially changes the data
   model.
6. **Car Data Files page — is this meant to surface the existing `vag_pipeline` /
   `data-export` outputs (decoded OBD reports, DTC catalog, coding/adaptation snapshots), or
   is it a more general document/spec-sheet store?** This materially changes Phase 3's future
   backend design — get this answered before building past the stub in Phase 3.

---

## Suggested execution order

1. **Phase 1** first, always — establish a correct, current baseline before any UI changes, so
   later visual diffs are attributable to Phase 2's work alone.
2. **Phase 2** — the bulk of the effort; work top-to-bottom through the checklist (2.1 → 2.10).
3. **Phase 3** — smaller and mostly mechanical once Phase 2's new component styles
   (`.utility-header`, pill badges, empty-state pattern) exist to reuse.
4. **Phase 4** — full verification pass.
5. **Phase 5** — housekeeping/cleanup, then hand back for review.

## Non-goals — do not do these as part of this plan

- Do not fine-tune or swap any model.
- Do not modify `specverify.py`'s verification logic or `retrieve.py`'s grounding-gate
  thresholds (`cos_floor`, `bm25_floor`, `coverage_floor`) — those are safety-critical and
  outside this plan's scope.
- Do not build full CRUD for Car Maintenance or Car Data Files beyond the agreed stub without
  explicit sign-off (Open Decisions 5–6).
- Do not commit `out/`, `.env`, or any manual PDFs.
- Do not silently resolve any of the six Open Decisions above by picking whichever is easiest
  to build — flag them and get an answer, per this project's own stated principle of never
  silently resolving ambiguity (see `CLAUDE_CODE_HANDOVER.md`'s rule about video/manual
  conflicts — same spirit applies here to product decisions).
