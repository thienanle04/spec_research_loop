# Loop Session title is last-write-wins

`PATCH` Loop Session title does not take `expected_version` and does not increment the aggregate version. Last write wins. Title is a list/header label, not part of the Research Spec Confirm freezes, so putting it on the same concurrency boundary made rename 409 Confirm and Working Draft persist.

**Status:** accepted; amends [0021](./0021-aggregate-loop-session-version.md).

**Considered options:** keep title on the aggregate version and only split SPA status chips; a separate `title_version`; last-write-wins without bumping version (chosen).

**Why:** ADR 0021’s race is Confirm vs narrative/Cards. Title is not in that freeze. Cross-tab rename overwrites; that is acceptable for a label.
