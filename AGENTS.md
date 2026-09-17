# Agent execution rules

## Authoritative project tracker

`docs/automotive-rag/CC_Workshop_Planning_Tracker.xlsx` is the authoritative execution tracker for the CC Workshop project. The approved implementation plan describes intended design; Git history and evidence prove implementation; the tracker must accurately reflect both.

### Mandatory tracker synchronization

No task or subtask may be declared **Done**, handed over as complete, or used as the basis for starting its dependent task until all of the following are true:

1. The implementation or documentation work is complete.
2. Required tests and acceptance checks have been run and their actual results are known.
3. Required evidence artifacts have been created or updated.
4. The corresponding tracker rows are updated with the real status, evidence paths, test results, and commit information.
5. The tracker is regenerated/validated using the repository tracker tooling.
6. The updated tracker and its machine-readable execution snapshot are committed and pushed with the completed work or in the immediately following reconciliation commit.

Code that is complete while the tracker is stale is **not fully complete**. Its status must be treated as `In Progress / Tracker reconciliation required` until synchronization is finished.

### Pre-work reconciliation gate

Before starting a new CC-T### task, compare the checked-out Git branch/HEAD and relevant evidence against the tracker. If Git contains completed work not represented by the tracker, or the tracker claims completion that cannot be proven from Git/evidence, stop normal task progression and reconcile the discrepancy first.

### Evidence integrity

- Never invent, predict, or copy a commit SHA that has not actually been created and resolved in this repository.
- Never mark work Done solely because it exists locally, in an unpushed commit, or in an unrelated branch.
- Record the exact branch and resolvable commit SHA for completed implementation evidence.
- Record actual test counts/results, not expected results.
- Missing applicability, provenance, or acceptance evidence must remain explicitly unresolved rather than being treated as success.

### Branch discipline

Before completing a task, identify the canonical development branch for that work and ensure the tracker describes that branch's actual state. Do not silently treat `main`, backup branches, feature branches, and the workbook as interchangeable project states.

### Handover requirement

Every implementation handover must state:

- current branch and HEAD SHA;
- task/subtask status;
- tests executed and results;
- tracker synchronization status;
- remaining blockers or acceptance gates.

If tracker synchronization has not succeeded, the handover must say so explicitly and must not describe the task as Done.
