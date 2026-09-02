# Claims is the only Workflow Node for Claim and Evidence Cards

Loop Stage Claims/evidence has one Workflow Node (`claims`). Confirm `claims` freezes both Card kinds and requires at least one non-blank Claim Card and one non-blank Evidence Card. Generate is one `/claims/generate`. `evidence` is not a Workflow Node; old Decision rows may still name it. Confirm `claims` marks `experiment_plan`, `evidence_judge`, and `experiment_judge` Stale (not `gap_judge` or `contribution_judge`). Existing sessions mint a silent combined `claims` Stage Revision from the two former heads, with no Decision.

**Considered options:** keep two Confirms off the rail; one Confirm that auto-Confirms a hidden `evidence` node; union of former `evidence` Judge edges onto `claims`.

**Why:** Two nodes in one rail stop left Evidence unreachable after Confirm `claims`. A hidden second Confirm is auto-Confirm. Gap Judge verifiers read the Gap Card and related-work passages, not Claim/Evidence Cards, so those Judge edges do not follow the merge.
