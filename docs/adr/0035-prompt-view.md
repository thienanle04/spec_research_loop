# Prompt View derived from Context Projection

LLM generate/Judge calls receive a **Prompt View**: a Workflow-Node-scoped, prompt-ready slice of a Context Projection. Context Projection stays the full in-process assembly (upstream Stage Revisions, Working Draft, StagePort `projected`). Day one, `loop` owns `prompt_view(node, projection)` and `project_prompt_view(...)`; Spec contribution / claims / experiment / feasibility stop dumping raw Context Projection into prompts. Idea, Research, and Judges adopt the same helper later.

Spec Prompt Views keep confirmed Card texts, Gap statement, selected contribution material, and the current node's Working Draft; they drop grilling turn transcripts, Related Work abstracts, storage keys, empty projectors, and internal ids. Contribution adds compact studies. Claims adds citation passages plus source metadata (title, year, venue, verification_status) so generate can cite keys that exist. Feasibility adds a thin experiment-plan summary. Gap and Contribution Judges omit `experiment_plan`. Conference Judge adds the feasibility report (resources, bottlenecks/risks, mitigations). Evidence Judge passages and claim-citation triples include the same source metadata.

**Considered options:** thin Context Projection for every caller; ad-hoc `json.dumps(context)` per module; extend StagePort with `prompt_project`.

**Why:** Invalidation and typed freeze still need a full Projection (ADR 0009, ADR 0013). Prompt dumps were both noisy and expensive. A named Prompt View keeps that split explicit in the glossary and avoids each workflow inventing a different slim shape.
