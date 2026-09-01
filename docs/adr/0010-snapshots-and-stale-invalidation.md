# Immutable snapshots, dual Spec Version pointers, DAG stale-marking

Current Loop Session state is one Working Draft plus confirmed Stage Revisions. Decisions are an append-only audit, not the source we replay. Each Loop Session tracks a Produced Spec Version (last minted, for history and diff) and a Valid Spec Version (input to Context Projection; absent when stale). Confirming feasibility mints a new Spec Version, including when Confirm hash-matches the current feasibility Stage Revision after Valid Spec Version was cleared. Changing a confirmed workflow node marks downstream nodes stale, keeps history, and does not auto-run LLM or Judge work — opening an available empty or Stale Workflow Node runs `recompute-prepare` for that Loop Stage (ADR 0033).

**Considered options:** event-source current state from Decisions; a single “latest spec” pointer; eager full-pipeline recompute.

**Why:** Replay is expensive and easy to drift. A stale Produced Spec Version must remain visible for diff, but Judges must not read it. LLM work is costly; TOPIC asks to re-run related verifiers after the user chooses a fix, not to autopilot the pipeline.
