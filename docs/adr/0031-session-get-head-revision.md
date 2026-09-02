# Session GET embeds the Node Head Stage Revision

GET Loop Session includes `head_revision` (`narrative`, `card_snapshot`) on each `NodeHeadResponse` so the workbench can render another Workflow Node read-only without PATCHing Working Draft. Empty heads send `null`. History beyond the Node Head is not listed.

**Status:** accepted; extends ADR 0020.

**Considered options:** a per-node head-revision GET (rejected—extra round-trip on every tab/Back/Next); embed only the viewed node (rejected—session query cache would churn with `?node=`).

**Why:** Browse must show confirmed (and Stale) Stage Revisions without making that node the Working Draft. The service already loads those revisions to assemble a Spec Version.
