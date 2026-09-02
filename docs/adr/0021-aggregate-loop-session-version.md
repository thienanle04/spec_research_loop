# Aggregate version for Loop Session mutations

Every Loop Session has one monotonically increasing version. Working Draft edits, Card writes, confirm, recompute-prepare, and reopening a current Workflow Node must supply the expected version and atomically increment it; a mismatch returns a typed `version_conflict` response. Title persist is last-write-wins ([0032](./0032-title-last-write-wins.md)). The SPA serializes autosaves and preserves local content for explicit conflict resolution.

**Status:** accepted; title persist superseded by [0032](./0032-title-last-write-wins.md).

**Considered options:** per-resource versions plus an aggregate confirm token; HTTP ETags with `If-Match`; last-write-wins.

**Why:** Confirm freezes narrative and Cards as one aggregate, so resource-only checks leave a race between the final autosave and confirmation. One version gives every command the same concurrency boundary and makes cross-tab or cross-device conflicts visible, at the accepted cost of serializing otherwise independent writes.
