# Tracker follow-up review

Reviewed saved snapshot `CC-SNAPSHOT-20260910122434497-a12d72b2`. This was a read-only workbook/JSON review plus in-memory probes. No Excel or output JSON file was saved by this agent. The stale applied `tracker-updates.json` was not read or reused. Only the existing builder was patched; the coordinator owns its next normal execution.

## Findings and fixes

### Imported timestamps were exported as Excel serial numbers

The saved JSON showed mixed timestamp types after rebuilding from Excel:

| Table | Field | ISO strings | Excel serial numbers |
|---|---|---:|---:|
| Tasks | Updated at | 3 | 33 |
| Steps | Updated at | 8 | 136 |
| Steps | Execution finished at | 8 | 0 |
| Decisions | Updated at | 1 | 13 |
| Evidence | Observed at | 9 | 3 |

Cause: artifact-tool imports typed Excel dates as numeric serials. The builder previously normalized values only while preparing Excel writes, and left the record objects used for JSON unchanged.

Fix in `work/build-tracker.mjs`: normalize every populated timestamp field after importing saved state and applying coordinator updates, before workbook authoring and JSON serialization. The builder uses its own Excel 1900 date system. Date-only inputs are UTC midnight; timezone-free date/time inputs are explicitly UTC; offset-qualified inputs retain their instant; invalid date inputs fail clearly. Blank timestamp fields stay blank.

The probe extracted and executed the actual patched helper, without importing or executing the builder:

```json
{
  "timestamp_probe": "passed",
  "normalized": 214,
  "serials": 185,
  "strings": 29,
  "sample_serial": 46275.51530535879,
  "sample_iso": "2026-09-10T12:22:02.383Z"
}
```

All populated timestamp values normalized to UTC ISO strings. Serial-to-date-to-serial error was below one millisecond. Explicit tests covered a timezone-free UTC time, a `-04:00` offset, a date-only value, a blank and an invalid value. All passed. Excel timestamps and generated JSON now use millisecond precision consistently.

### README title clipped at its existing row height

Visual review of `work/previews/README.png` confirmed that the second title line was clipped by the 30-point first row. The same title at 48 points was rendered in memory and visually inspected successfully. The probe is `work/previews/README-title-probe.png`. The builder now uses that row height; no schema or content change was needed.

### Matching JSON snapshots were not archived

The existing builder archived the prior XLSX alone. It now reads the prior JSON at startup and archives the bytes beside the prior XLSX only when the JSON snapshot ID matches the imported workbook's previous snapshot ID. A mismatched or unreadable JSON file is reported and not misrepresented as a matching archived pair. Archive filenames are constrained to safe filename characters, with the workbook hash as fallback.

This change was syntax-checked. Its first normal execution and filesystem verification remain with the coordinator.

### Evidence paths and hashes need an audit trail

The coordinator identified mutable captures for early evidence records. The builder now emits a nonblocking `work/evidence-reference-review.json` and includes the review in generated JSON. It records:

- Whether a local capture exists and is a file.
- Its current hash and the recorded historical hash.
- Which evidence records supersede it.
- Whether it points to an output about to be replaced by a new snapshot.
- Remote references as not fetched by workbook authoring.

Historical records are not deleted, silently rewritten or rejected because their capture changed. Durable acceptance proof should point to immutable checkpoint files. The coordinator is correcting early records with superseding evidence.

## Append-row formula probe

Imported the saved workbook into memory, then appended an artificial `CC-T002-S05` engineering/initial step with simulated Status `Done`. This probe row was never exported and does not represent completed work.

Observed:

| State | Initial engineering steps | Steps done | CC-T002 step total | CC-T002 done | CC-T002 verified ratio |
|---|---:|---:|---:|---:|---:|
| Before append | 124 | 0 | 4 | 0 | 0 |
| Immediately after artifact-tool table append | 124 | 0 | 4 | 0 | 0 |
| After assigning the same structured-reference formulas again | 125 | 1 | 5 | 1 | 0.2 |
| After changing appended status from Done to Blocked | 125 | 0 | 5 | 0 | 0 |

The table expands correctly, but artifact-tool keeps imported formula caches stale until the dependent formulas are reassigned. Once reassigned, subsequent cell edits recalculate normally. The production builder already reconstructs tables and reassigns all dependent formulas on each normal run, so no additional formula or schema patch is needed for that workflow.

This proves the builder's recalculation approach with table extension. It is not a claim that native Microsoft Excel's interactive append behavior was tested.

## Validation and handoff

- Bundled Node syntax check of the patched builder passed.
- No normal builder run was executed by this agent.
- No application code was changed.
- No output XLSX or JSON was saved by this agent.
- The coordinator should use a fresh update file bound to the current snapshot, run the builder once, verify that timestamp fields are ISO in the generated JSON, inspect the updated title, and confirm matching old XLSX/JSON files appear in `work/tracker-snapshots`.
- Review `work/evidence-reference-review.json` after that run. Old superseded mismatches are historical observations, not fresh engineering failures.
