# Preserve suspended Working Draft data across Workflow Node navigation

The Loop Session keeps one active Working Draft and a node-keyed narrative snapshot for Workflow Nodes that the Account temporarily leaves. Moving to another current node saves the active narrative; returning restores the saved narrative before falling back to the current Stage Revision. `recompute-prepare` preserves an Empty node's saved narrative and typed working rows when unconfirmed generated work exists. Stale nodes still reset from their last Stage Revision.

**Considered options:** always reset Empty nodes; keep only the single active narrative; implicitly Confirm generated output before navigation.

**Why:** an Account may generate Related Work, return to Research Inputs, and Continue without confirming the Search first. Empty describes the absence of a confirmed Stage Revision, not the absence of valuable working data. Discarding that data makes navigation destructive, while implicit Confirm would bypass the explicit Decision boundary.

Supersedes ADR 0016 only where it requires resetting an Empty Workflow Node that already has suspended Working Draft data.
