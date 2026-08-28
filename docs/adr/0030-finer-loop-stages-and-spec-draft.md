# Finer Loop Stages, navigable Contribution, and Spec Draft

Loop Stage groupings match the session rail: Grilling; Related work (`research_inputs`, `related_work` only); Gap; Contribution; Claims/evidence; Experiment planning; Spec Draft (no nodes); Independent judges; Readiness. `recompute-prepare` still resets only Stale or empty nodes inside the requested Loop Stage (ADR 0016), so prepare on Related work no longer touches gap or contribution. Spec Draft is a read-only Loop Stage for the Produced Spec Version (Valid vs Stale); it is not a Workflow Node and does not mint or Confirm a Spec Version—feasibility Confirm still does (ADR 0010, 0014). Workflow Node set and invalidation edges are unchanged.

**Status:** accepted; partially supersedes ADR 0014’s “no separate navigable Contribution stage” and Related-work-includes-gap-and-contribution grouping.

**Considered options:** UI-only Nav Units with unchanged Loop Stage enum (rejected—Account-facing stage and prepare target would diverge); prepare per sub-tab Workflow Node only (rejected—multi-node stages should recompute together); Spec Version as a confirmable Workflow Node (rejected again, ADR 0014).

**Why:** The session workbench needs a denser rail and a dedicated place for Spec Version without inventing a second prepare vocabulary. Splitting Related work / Gap / Contribution keeps Confirm-per-node and the DAG while letting Accounts recompute gap without resetting related-work search state.
