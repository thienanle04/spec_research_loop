# Interpretation Confirm does not auto-Generate decomposition

Confirming `idea_interpretation` still advances the Working Draft to `idea_decomposition` (ADR 0018 handoff). The SPA no longer calls `idea` generate automatically; decomposition Generate is an explicit Account action, same as every other Workflow Node. After Confirm, the SPA follows the generic continue path and may `recompute-prepare` Grilling (ADR 0033). Decomposition Working Draft always shows the Generate Cards / Regenerate Cards panel (flip on whether Cards already exist).

**Considered options:** keep SPA auto-Generate after Confirm (ADR 0018); normalize away the in-confirm Working Draft handoff and rely only on prepare; navigate-only after handoff without prepare.

**Why:** Auto-Generate contradicted ADR 0033’s “LLM does not auto-run” and burned cost if the Account left after Confirm. Shared understanding remains its own Stage Revision; Cards still need an explicit Generate. Partially supersedes ADR 0018.
