# CC Workshop implementation checkpoint

Start with [the handover](CC_Workshop_Handover.md) and the repository-level [`AGENTS.md`](../../AGENTS.md) execution rules.

- [Excel planning and tracking workbook](CC_Workshop_Planning_Tracker.xlsx)
- [Machine-readable plan and execution snapshot](CC_Workshop_Implementation_Plan.json)
- [Approved implementation plan](CC_Workshop_Implementation_Plan.md)
- [Evidence file manifest](evidence-manifest.json)

The workbook is the authoritative execution tracker, but it must be reconciled against Git and evidence before relying on its status. A September 2026 audit found tracker/branch drift, including completed implementation not reflected in workbook status. Until that reconciliation is complete, Git history plus evidence are the proof of work and conflicting workbook rows must be treated as `Tracker reconciliation required` rather than assumed correct.

Tracker synchronization is now a mandatory definition-of-done requirement in `AGENTS.md`: completed work, actual test results, evidence, resolvable commit information, and the regenerated/validated tracker must be committed before a task can be handed over as Done or dependent work can proceed.

Evidence files retain their original bytes. Historical local paths are provenance, not portable installation instructions. Original user attachments remain local; their hashes are recorded. Superseded mutable evidence CC-E002 through CC-E004 is preserved in the tracker with replacement references CC-E149 through CC-E151.
