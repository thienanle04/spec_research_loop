# Interpretation stores an Idea Frame and Account notes

Each interpretation generate overwrites a model-authored Idea Frame (`intent`, `problem`, `research_question`) on the Working Draft and still appends a turn (preamble + Grilling Questions). The Account cannot edit the Idea Frame; they steer with Grilling Option answers and/or an Account note. Cluster Send is `{ expected_version }` plus complete `answers`, a non-empty note, or both. A note without answers skips the open cluster; skipped questions stay on the transcript. Confirm’s gate is ADR 0029 (complete Idea Frame, open clusters allowed). `exhausted` remains a hint. PATCH of Account turns (idea, answers, note) still truncates later turns (ADR 0025).

**Considered options:** treat the frame as Cards during grilling; make the frame Account-editable; keep answers-only cluster Send; gate Confirm on `exhausted`; let Confirm succeed with a blank frame.

**Why:** Grilling is shared understanding of research intent, shown in a fixed restatement the Account can Confirm, not early decomposition. A free-form note lets them correct the model without editing the frame. A blank frame cannot be the source of problem and research-question Cards (ADR 0028).

Extends ADR 0025. Supersedes that ADR’s “cluster Send is answers only.” Confirming interpretation still starts decomposition (ADR 0018). The cluster-closed Confirm gate here is superseded by ADR 0029.
