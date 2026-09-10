# Tracker builder handoff

`work/build-tracker.mjs` passed the bundled Node syntax check. It has not been run by the builder agent. The coordinator owns the authoring marker, workbook execution, verification, user preview and all execution-state changes.

## Run

1. Read-only source preview, when needed: `node work/build-tracker.mjs --source-preview`.
2. Inspect `work/previews/source.png` before first authoring.
3. Run the spreadsheet authoring marker exactly once as required by the spreadsheet skill.
4. Run `node work/build-tracker.mjs`.
5. Inspect all six worksheet previews and `README-progress.png`; inspect `work/tracker-validation.json`.

Normal execution produces the approved XLSX and JSON in outputs. It parses all 33 initial task sections plus three future table rows, generating 36 tasks and 144 task-specific steps. Full task implementation, acceptance and source Markdown are retained in JSON. Task acceptance criteria receive immutable `CC-R` IDs. The complete approved Markdown is included in JSON. All future tasks remain outside initial engineering formulas.

## Update contract

The optional input is `work/tracker-updates.json`. Use the exact approved Excel column names as field keys. Do not write calculated fields. Initial generation leaves CC-T000 In progress, every step Not started and all engineering work Not started. The builder does not claim its output has passed a human visual review.

```json
{
  "expectedSnapshotId": "COPY THE CURRENT Handover Snapshot ID",
  "sessionId": "ACTUAL SESSION ID IF KNOWN",
  "tasks": {
    "CC-T000": {
      "Status": "In progress",
      "Owner": "Coordinator",
      "Your notes": "Actual observations only"
    }
  },
  "steps": {
    "CC-T000-S01": {
      "Status": "Done",
      "Observed result": "Describe the actual input-preservation check",
      "Execution finished at": "ACTUAL ISO UTC TIMESTAMP",
      "Run ID": "ACTUAL RUN ID"
    }
  },
  "evidence": {
    "CC-E001": {
      "Status": "Done",
      "Captured where": "work/input-manifest.json",
      "Observed at": "ACTUAL ISO UTC TIMESTAMP",
      "Actual result": "Describe the actual observed hashes and result"
    }
  },
  "decisions": {},
  "handover": {
    "Working branch": "ACTUAL BRANCH ONLY",
    "Actual HEAD": "ACTUAL COMMIT ONLY",
    "Last verified execution": "ACTUAL OBSERVED CHECK",
    "Last verified evidence IDs": "[\"CC-E001\"]",
    "Next concrete action": "Next specific eligible action"
  }
}
```

The example is a schema illustration and must not be used as execution evidence. Omit `expectedSnapshotId` on the initial build, or set it to an empty string. On subsequent runs use the current saved snapshot. A stale expected snapshot intentionally fails. Replace or remove already-applied update files before future runs so an old patch does not overwrite newer intent.

`tasks`, `steps`, `decisions` and `evidence` accept either objects keyed by ID or arrays of records containing the identity column. New decision/evidence rows can be appended through updates. New tasks and steps require an explicit plan migration. Existing Excel row values, state inputs, timestamps, notes, decisions and Handover values are loaded before patches are applied; formulas are regenerated. Unexpected schema changes cause a failure rather than silently dropping columns.

## Stable evidence assignment

- Task ordinal `n`, step ordinal `s`: evidence ID is `CC-E` followed by `n*4+s`, padded to three digits.
- CC-T000-S01 through S04 require CC-E001 through CC-E004.
- CC-T001-S01 through S04 require CC-E005 through CC-E008.
- The 144 task-step evidence requirements initially remain Not started.
- CC-E145 through CC-E147 record the three preserved-input hash checks, kind Source. These do not close any engineering task.
- New distinct execution attempts should receive new IDs; attach their IDs to the applicable step/task requirements and retain failed attempts. The initial requirement row can record the resulting acceptance observation with a link to that run. Supersedes ID preserves correction provenance.

## Completion checks enforced

- IDs are unique and dependencies resolve without cycles.
- All task/step release and work-class values are consistent.
- Done steps require a nonempty observed result and their completed required evidence.
- Done evidence requires actual result and observation time. Execution/Release evidence also needs a capture path, environment and Run ID.
- Done tasks require closed steps, Passed gate and complete required evidence. Engineering tasks require Execution or Release evidence.
- Waived tasks/steps require a rationale and linked decision.
- Formula values are independently reconciled against record counts. Formula errors cause failure.
- Initial engineering formulas count 31 tasks and 124 steps; Future has three tasks and is excluded.
- Preserved input hashes must match `work/input-manifest.json`.
- The output hash is compared immediately before replacement to detect a competing writer.
- Prior workbook bytes are archived under `work/tracker-snapshots` on subsequent runs.

## Remaining coordinator work

Run and verify the builder. Record the source-preview inspection, successful output checks and all-six-tab visual review as actual evidence. Then close CC-T000's four steps and task through the update file, rerun once, and show the resulting XLSX to the user. Application work is gated on this verified tracker foundation.

The builder never runs the authoring marker, never edits application code, never changes the original workbook in Downloads, and never claims a commit or branch exists.
