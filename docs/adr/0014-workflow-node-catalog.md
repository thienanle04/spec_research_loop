# Loop owns a fixed Workflow Node catalog

**Status:** accepted for Workflow Node set, Node Heads, and “Spec Version is not a Workflow Node”; Loop Stage groupings for Related work / Contribution superseded by ADR 0030.

`loop` creates a Node Head per Workflow Node when a Loop Session is born. The catalog is: `idea_interpretation`, `idea_decomposition`, `research_inputs`, `related_work`, `gap`, `contribution`, `claims`, `experiment_plan`, `feasibility`, `gap_judge`, `contribution_judge`, `evidence_judge`, `experiment_judge`, `conference_judge`, `aggregator`. `evidence` is not a Workflow Node (ADR 0044); it may still appear on Decision history. Readiness (and, per ADR 0030, Spec Draft) is a Loop Stage with no Node Head. Confirming `feasibility` mints a Spec Version; `spec_version` is not a Workflow Node. Catalog, Loop Stage groupings, and invalidation edges are constants in `loop`, not rows.

**Considered options:** idea→feasibility heads only until Judges exist; treat Spec Version and Readiness as confirmable Workflow Nodes.

**Why:** Stale marking follows the invalidation graph in `docs/for-human/backend.mmd`. If Judge Node Heads do not exist, a contribution edit cannot mark `contribution_judge` Stale. Readiness is a read model (no generate). Spec Version is an assembly of Stage Revisions, not another confirmable node (ADR 0010).
