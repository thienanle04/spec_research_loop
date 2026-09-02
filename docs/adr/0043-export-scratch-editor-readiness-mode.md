# Export Scratch editor is a Readiness URL mode

The Export Scratch markdown source-and-preview workspace is a Readiness mode addressable as `export_scratch=1` plus `spec_version`, not a Loop Stage. The Loop Stage rail and stage-path nav are hidden while it is open; Done returns to the rest of Readiness. Overlay edits autosave last-write-wins; Save Snapshot is the explicit checkpoint.

**Status:** accepted

**Considered options:** a new Loop Stage (rejected — Export Scratch is not a confirmable Workflow Node group); ephemeral editor state with no URL (rejected — refresh would dump the Account out of the workspace); treating the query as another `stage` value (rejected — Readiness criteria still follow the Valid Spec Version).

**Why:** Bookmarking must reopen the same Spec Version's Export Scratch without implying navigation away from Readiness or changing which Spec Version the criteria follow.
