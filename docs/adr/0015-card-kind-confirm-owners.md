# Each Card kind has one confirming Workflow Node

A confirm freezes and hashes only the Card kinds that Workflow Node owns. Editing any other kind while it is the Working Draft is rejected. Claim and Evidence Cards are both owned by `claims` only (ADR 0044). Constraint and open-question Cards are owned by `idea_decomposition` only. `experiment_plan` freezes narrative (and later typed experiment rows), not constraint Cards. Changing a constraint later means reconfirming Grilling, which marks downstream Workflow Nodes Stale.

**Considered options:** constraint Cards also owned by `experiment_plan`; two glossary kinds (idea constraint vs experiment constraint); every confirm snapshots every Card.

**Why:** Dual ownership makes “wrong node” unenforceable and picks the wrong stale fan-out. Experiment-only constraint Cards would hide idea-level limits from Grilling. Splitting kinds is extra glossary for a student slice. Wide stale on a constraint edit is the accepted cost of A1.
