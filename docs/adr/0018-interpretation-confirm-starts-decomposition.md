# Confirming interpretation starts decomposition

When `idea_interpretation` is confirmed (shared understanding; ADR 0029 gate: Idea Frame intent, problem, and research_question non-blank), `loop` sets the Working Draft to `idea_decomposition`. Confirming `idea_decomposition` does not auto-enter Related work. Further prompts while the Working Draft is `idea_decomposition` stay there and refine Cards; reopening questions is `PATCH` Working Draft to `idea_interpretation` (ADR 0019).

**Status:** Partially superseded by ADR 0038 — decomposition Generate is no longer started automatically after Confirm; the Working Draft handoff remains.

**Considered options:** client must `recompute-prepare(Grilling)` to begin decomposition; one SSE with no interpretation confirm; two explicit generates and no auto.

**Why:** Shared understanding is its own Stage Revision (Context Projection / history). Generate stays on `idea` (ADR 0012). Extends ADR 0017.
